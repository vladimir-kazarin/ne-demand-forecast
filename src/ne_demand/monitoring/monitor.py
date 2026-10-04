"""One monitoring cycle (run hourly): freshness, forecast error, input drift, alerts.

Writes, under {root}/published/monitoring/:
    status.json             latest result of every check (read by the watchdog and app)
    drift_history.parquet   one row per day of drift checks (and drills)
    drift_latest.parquet    per-feature PSI/KS context for the latest window
    reports/drift_<day>.html  Evidently data-drift report for that window
"""

from __future__ import annotations

import json
import logging
import tempfile
import warnings
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import fsspec
import pandas as pd

from ne_demand.config import LOCAL_TZ
from ne_demand.evaluation.events import read_events
from ne_demand.features.build import TEMP_COLUMNS, target_hours, training_frame
from ne_demand.monitoring.alerts import AlertState, send_alert
from ne_demand.monitoring.drift import (
    CONTEXT_FEATURES,
    DriftResult,
    check_drift,
    current_days,
    inject_shift,
    seasonal_reference_days,
)
from ne_demand.monitoring.freshness import check_freshness
from ne_demand.monitoring.performance import check_performance, rolling, update_errors
from ne_demand.processing import read_processed

log = logging.getLogger(__name__)

MON = "published/monitoring"


def _path(root: str, rel: str):
    return fsspec.core.url_to_fs(f"{root.rstrip('/')}/{MON}/{rel}")


def _read_parquet(root: str, rel: str) -> pd.DataFrame:
    fs, p = _path(root, rel)
    if not fs.exists(p):
        return pd.DataFrame()
    with fs.open(p, "rb") as f:
        return pd.read_parquet(f)


def _write_parquet(root: str, rel: str, df: pd.DataFrame) -> None:
    fs, p = _path(root, rel)
    fs.makedirs(p.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(p, "wb") as f:
        df.to_parquet(f, index=False)


def production_holdout_mape(root: str) -> float | None:
    """Holdout MAPE of the current production version, from the event log."""
    ev = read_events(root)
    moves = ev[ev["event"].isin(["promoted", "rolled_back"])]
    if moves.empty:
        return None
    version = moves.iloc[-1]["version"]
    reg = ev[(ev["event"] == "registered") & (ev["version"] == version)]
    return float(reg.iloc[-1]["candidate_mape"]) if not reg.empty else None


def drift_inputs(root: str, end_day: date, lags: list[int], issue_local: time):
    """(reference, current, training range) for the week ending `end_day`, or None
    when there is not yet a year of history for the seasonal reference."""
    cur = current_days(end_day)
    ref = seasonal_reference_days(cur)
    load_df = read_processed(root, "load_hourly")
    weather_df = read_processed(root, "weather_hourly")
    if load_df.empty or weather_df.empty:
        return None
    first_needed = target_hours(ref[0])[0] - pd.Timedelta(hours=max(lags))
    if weather_df["time"].min() > target_hours(ref[0])[0] or load_df["time"].min() > first_needed:
        return None
    load = load_df.set_index("time")["load_mw"]
    temps = weather_df.set_index("time")[TEMP_COLUMNS]
    frame = training_frame(load, temps, ref + cur, issue_local, lags)
    reference = frame[frame["target_day"].isin(ref)]
    current = frame[frame["target_day"].isin(cur)]
    history = weather_df[weather_df["time"] < target_hours(cur[0])[0]]
    return reference, current, (history[TEMP_COLUMNS].min(), history[TEMP_COLUMNS].max())


def _evidently_report(
    root: str, day: date, reference: pd.DataFrame, current: pd.DataFrame
) -> str | None:
    try:
        from evidently.metric_preset import DataDriftPreset
        from evidently.report import Report
    except ImportError:
        log.info("evidently not installed; skipping HTML drift report")
        return None
    report = Report(metrics=[DataDriftPreset()])
    with warnings.catch_warnings():  # pandas FutureWarnings from inside Evidently 0.6
        warnings.simplefilter("ignore", FutureWarning)
        report.run(
            reference_data=reference[CONTEXT_FEATURES], current_data=current[CONTEXT_FEATURES]
        )
    rel = f"reports/drift_{day.isoformat()}.html"
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "report.html"
        report.save_html(str(local))
        fs, p = _path(root, rel)
        fs.makedirs(p.rsplit("/", 1)[0], exist_ok=True)
        fs.put_file(str(local), p)
    return rel


def _history_row(day: date, now: datetime, r: DriftResult, drill: dict | None) -> dict:
    station = max(r.spread_shift_c, key=r.spread_shift_c.get)
    return {
        "day": day,
        "checked_at": now,
        "drill": bool(drill),
        "injected": json.dumps(drill) if drill else None,
        "max_spread_shift_c": r.spread_shift_c[station],
        "max_spread_station": station,
        "out_of_range_share": r.out_of_range_share,
        "alerts": " | ".join(r.alerts) or None,
        **{f"spread_shift_{k}": v for k, v in r.spread_shift_c.items()},
    }


def run_monitor(
    root: str,
    now: datetime | None = None,
    inject: dict[str, float] | None = None,
    lags: list[int] | None = None,
    issue_local: time = time(10, 30),
    send: Callable[[str, str], None] = send_alert,
) -> dict:
    now = now or datetime.now(UTC)
    lags = lags or [24, 48, 168]
    checks = check_freshness(root, now)

    errors = update_errors(root)
    checks["forecast_error"] = (
        "; ".join(check_performance(errors, production_holdout_mape(root))) or None
    )

    end_day = pd.Timestamp(now).tz_convert(LOCAL_TZ).date() - timedelta(days=1)
    history = _read_parquet(root, "drift_history.parquet")
    real = history[~history["drill"]] if not history.empty else history
    done_today = not real.empty and (real["day"] == end_day).any()
    drift_note = None

    if inject or not done_today:
        inputs = drift_inputs(root, end_day, lags, issue_local)
        if inputs is None:
            drift_note = "not enough history for a seasonal reference yet"
        else:
            reference, current, training_range = inputs
            new_rows = []
            # The real daily check always runs; a drill never replaces it.
            if not done_today:
                result = check_drift(reference, current, training_range)
                new_rows.append(_history_row(end_day, now, result, None))
                _write_parquet(root, "drift_latest.parquet", result.context.assign(day=end_day))
                _evidently_report(root, end_day, reference, current)
                real = pd.concat([real, pd.DataFrame(new_rows[-1:])], ignore_index=True)
            if inject:
                drill = check_drift(reference, inject_shift(current, inject), training_range)
                new_rows.append(_history_row(end_day, now, drill, inject))
                summary = "; ".join(drill.alerts) or "no alert fired"
                send(
                    f"[DRILL] Injected input shift {inject} into the week ending {end_day}. "
                    f"Result: {summary}",
                    "[ne-demand] DRILL: injected input shift",
                )
                drift_note = f"drill: {summary}"
            _write_parquet(
                root,
                "drift_history.parquet",
                pd.concat([history, pd.DataFrame(new_rows)], ignore_index=True),
            )

    if not real.empty:  # drift state comes from the latest real (non-drill) check
        checks["input_drift"] = real.iloc[-1]["alerts"] or None

    sent = AlertState(root, send).update(checks, now)
    status = {
        "checked_at": now.isoformat(),
        "checks": {k: (v or "ok") for k, v in checks.items()},
        "alerts_sent": sent,
        "rolling_7d": rolling(errors, 7) if not errors.empty else None,
        "rolling_30d": rolling(errors, 30) if not errors.empty else None,
        "drift_note": drift_note,
    }
    fs, p = _path(root, "status.json")
    fs.makedirs(p.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(p, "w") as f:
        json.dump(status, f, indent=2, default=str)
    log.info("monitor: %s; sent %s", status["checks"], sent)
    return status
