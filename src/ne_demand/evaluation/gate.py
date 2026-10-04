"""Evaluation gate and rollback.

The gate scores the candidate and the production model on the same holdout:
the candidate's own holdout window, recomputed on current data. The candidate
never trained on it, and production was trained earlier on even older data,
so neither model has seen those days. Promotion requires

    candidate MAPE <= production MAPE * (1 - margin)   and
    candidate MAPE <  naive baseline MAPE

Every decision is recorded on the candidate version (tags) and in the event log.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, time, timedelta

import lightgbm as lgb
import pandas as pd

from ne_demand.evaluation.events import append_event
from ne_demand.evaluation.metrics import mape
from ne_demand.features.build import TEMP_COLUMNS, target_hours, training_frame
from ne_demand.forecast.baseline import same_hour_last_week
from ne_demand.processing import read_processed
from ne_demand.training import tracking
from ne_demand.validation.schemas import validate_load, validate_weather

log = logging.getLogger(__name__)

DEFAULT_MARGIN = 0.02


@dataclass
class GateResult:
    decision: str  # promoted | rejected | skipped
    reason: str
    candidate_version: str
    production_version: str | None
    candidate_mape: float | None = None
    production_mape: float | None = None
    naive_mape: float | None = None
    holdout_start: str | None = None
    holdout_end: str | None = None


def _days(start: str, end: str) -> list[date]:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def _holdout_inputs(root: str, days: list[date], max_lag: int) -> tuple[pd.Series, pd.DataFrame]:
    start, end = target_hours(days[0])[0], target_hours(days[-1])[-1] + pd.Timedelta(hours=1)
    lag_start = start - pd.Timedelta(hours=max_lag)
    load_df = read_processed(root, "load_hourly")
    load_df = load_df[(load_df["time"] >= lag_start) & (load_df["time"] < end)]
    weather_df = read_processed(root, "weather_hourly")
    weather_df = weather_df[(weather_df["time"] >= start) & (weather_df["time"] < end)]
    validate_load(load_df, lag_start, end)
    validate_weather(weather_df, start, end)
    return load_df.set_index("time")["load_mw"], weather_df.set_index("time")[TEMP_COLUMNS]


def score(
    booster: lgb.Booster, meta: dict, load: pd.Series, temps: pd.DataFrame, days: list[date]
) -> tuple[float, pd.Series]:
    """MAPE of one model on `days`, with features built from its own config."""
    cfg = meta["config"]
    frame = training_frame(
        load, temps, days, time.fromisoformat(cfg["issue_time_local"]), cfg["lag_hours"]
    )
    pred = pd.Series(booster.predict(frame[meta["features"]]), index=frame.index)
    return mape(frame["load_mw"], pred), frame["load_mw"]


def run_gate(root: str, candidate: str | None = None, margin: float = DEFAULT_MARGIN) -> GateResult:
    candidate = candidate or tracking.alias_version(tracking.CANDIDATE)
    if candidate is None:
        raise LookupError("no candidate version to evaluate")
    production = tracking.production_version()

    if production is None:
        result = GateResult("promoted", "no production version yet", candidate, None)
    elif production == candidate:
        result = GateResult("skipped", f"v{candidate} is already production", candidate, production)
    else:
        cand_booster, cand_meta = tracking.load_version(candidate)
        prod_booster, prod_meta = tracking.load_version(production)
        window = cand_meta["data_window"]
        days = _days(window["holdout_start"], window["holdout_end"])
        max_lag = max(cand_meta["config"]["lag_hours"] + prod_meta["config"]["lag_hours"])
        load, temps = _holdout_inputs(root, days, max_lag)

        cand_mape, actual = score(cand_booster, cand_meta, load, temps, days)
        prod_mape, _ = score(prod_booster, prod_meta, load, temps, days)
        naive_mape = mape(actual, same_hour_last_week(load, actual.index))
        needed = prod_mape * (1 - margin)
        if cand_mape >= naive_mape:
            decision, reason = (
                "rejected",
                (f"does not beat the naive baseline ({cand_mape:.2f}% vs {naive_mape:.2f}%)"),
            )
        elif cand_mape <= needed:
            decision, reason = (
                "promoted",
                (
                    f"MAPE {cand_mape:.2f}% vs production v{production} {prod_mape:.2f}% "
                    f"(needed <= {needed:.2f}%, {margin:.0%} margin)"
                ),
            )
        else:
            decision, reason = (
                "rejected",
                (
                    f"MAPE {cand_mape:.2f}% vs production v{production} {prod_mape:.2f}%: "
                    f"not {margin:.0%} better (needed <= {needed:.2f}%)"
                ),
            )
        result = GateResult(
            decision,
            reason,
            candidate,
            production,
            cand_mape,
            prod_mape,
            naive_mape,
            window["holdout_start"],
            window["holdout_end"],
        )

    _record(root, result)
    return result


def _record(root: str, r: GateResult) -> None:
    tracking.set_version_tags(
        r.candidate_version,
        {
            f"gate_{k}": ("" if v is None else v)
            for k, v in asdict(r).items()
            if k not in ("candidate_version",)
        },
    )
    if r.decision == "skipped":
        log.info("gate skipped: %s", r.reason)
        return
    if r.decision == "promoted":
        tracking.promote(r.candidate_version, f"gate: {r.reason}")
    append_event(
        root,
        r.decision,
        r.candidate_version,
        r.reason,
        from_version=r.production_version,
        candidate_mape=r.candidate_mape,
        production_mape=r.production_mape,
        naive_mape=r.naive_mape,
        holdout_start=r.holdout_start,
        holdout_end=r.holdout_end,
    )
    log.info("gate %s v%s: %s", r.decision, r.candidate_version, r.reason)


def rollback(root: str, reason: str) -> tuple[str, str]:
    """Return production to the version it replaced. Returns (from, to)."""
    current = tracking.production_version()
    if current is None:
        raise LookupError("no production version to roll back")
    previous = tracking.version_tags(current).get("previous_production", "none")
    if previous in ("", "none"):
        raise LookupError(f"v{current} has no previous production version to roll back to")
    tracking.promote(previous, f"rollback from v{current}: {reason}")
    append_event(root, "rolled_back", previous, reason, from_version=current)
    log.info("rolled back production v%s -> v%s (%s)", current, previous, reason)
    return current, previous
