"""Config-driven LightGBM training with a fixed holdout scored against benchmarks."""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import UTC, date, datetime, timedelta

import lightgbm as lgb
import pandas as pd

from ne_demand.config import LOCAL_TZ, TrainConfig
from ne_demand.evaluation.metrics import mape
from ne_demand.features.build import TEMP_COLUMNS, target_hours, training_frame
from ne_demand.forecast.baseline import same_hour_last_week
from ne_demand.processing import read_processed
from ne_demand.training.model_store import save_model
from ne_demand.validation.schemas import validate_load, validate_weather

log = logging.getLogger(__name__)

NON_FEATURES = ["load_mw", "target_day"]


def git_commit() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.call(["git", "diff", "--quiet", "HEAD"]) != 0
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def last_complete_day(load: pd.DataFrame) -> date:
    last_hour_end = load["time"].max() + pd.Timedelta(hours=1)
    return last_hour_end.tz_convert(LOCAL_TZ).date() - timedelta(days=1)


def _iso_same_day(root: str) -> pd.Series:
    iso = read_processed(root, "iso_forecast")
    if iso.empty:
        return pd.Series(dtype=float)
    same = iso[iso["vintage"] == "same_day"].sort_values("forecast_time")
    return same.drop_duplicates("time", keep="last").set_index("time")["iso_forecast_mw"]


def train(cfg: TrainConfig, root: str, end_day: date | None = None) -> dict:
    load_df = read_processed(root, "load_hourly")
    weather_df = read_processed(root, "weather_hourly")
    if load_df.empty or weather_df.empty:
        raise FileNotFoundError(f"processed tables missing under {root}; run `ne-demand process`")

    end_day = end_day or last_complete_day(load_df)
    days = [end_day - timedelta(days=i) for i in range(cfg.window.lookback_days)][::-1]
    max_lag = max(cfg.lag_hours)
    window_start = target_hours(days[0])[0]
    window_end = target_hours(end_day)[-1] + pd.Timedelta(hours=1)

    load_df = load_df[(load_df["time"] >= window_start - pd.Timedelta(hours=max_lag))]
    load_df = load_df[load_df["time"] < window_end]
    weather_df = weather_df[
        (weather_df["time"] >= window_start) & (weather_df["time"] < window_end)
    ]
    validate_load(load_df, window_start - pd.Timedelta(hours=max_lag), window_end)
    validate_weather(weather_df, window_start, window_end)

    load = load_df.set_index("time")["load_mw"]
    temps = weather_df.set_index("time")[TEMP_COLUMNS]
    frame = training_frame(load, temps, days, cfg.issue_time_local, cfg.lag_hours)

    holdout_days = set(days[-cfg.window.holdout_days :])
    is_holdout = frame["target_day"].isin(holdout_days)
    train_df, hold_df = frame[~is_holdout], frame[is_holdout]
    features = [c for c in frame.columns if c not in NON_FEATURES]

    params = {
        "random_state": cfg.seed,
        "deterministic": True,
        "force_row_wise": True,
        "verbose": -1,
        **cfg.lightgbm,
    }
    model = lgb.LGBMRegressor(**params)
    model.fit(train_df[features], train_df["load_mw"])

    actual = hold_df["load_mw"]
    pred = pd.Series(model.predict(hold_df[features]), index=hold_df.index)
    metrics = {
        "holdout_mape": mape(actual, pred),
        "naive_holdout_mape": mape(actual, same_hour_last_week(load, actual.index)),
    }
    iso = _iso_same_day(root)
    if not iso.empty:
        # Same-day ISO vintage has more information than a day-ahead model (ADR 0002).
        metrics["iso_same_day_holdout_mape"] = mape(actual, iso.reindex(actual.index))

    trained_at = datetime.now(UTC)
    commit = git_commit()
    metadata = {
        "version": f"{trained_at:%Y%m%dT%H%M%SZ}-{commit[:7]}",
        "trained_at": trained_at.isoformat(),
        "git_commit": commit,
        "config": cfg.model_dump(mode="json"),
        "features": features,
        "data_window": {
            "train_start": str(days[0]),
            "train_end": str(min(holdout_days) - timedelta(days=1)),
            "holdout_start": str(min(holdout_days)),
            "holdout_end": str(end_day),
            "train_rows": len(train_df),
            "holdout_rows": len(hold_df),
        },
        "metrics": metrics,
    }
    save_model(root, model.booster_, metadata)
    log.info("trained %s: %s", metadata["version"], metrics)
    return metadata
