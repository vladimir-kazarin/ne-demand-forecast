"""Daily batch forecast: 24 (23/25 on DST days) hourly values for the next local day.

Nothing is written unless every input passes validation, so a broken input
never produces a published forecast.

    {root}/forecasts/date=YYYY-MM-DD/issued_at=YYYYMMDDTHHMMSSZ.parquet
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import fsspec
import pandas as pd

from ne_demand.config import LOCAL_TZ
from ne_demand.features.build import TEMP_COLUMNS, build_features, target_hours
from ne_demand.forecast.baseline import same_hour_last_week
from ne_demand.ingestion import weather
from ne_demand.ingestion.storage import write_raw
from ne_demand.processing import read_processed, weather_hourly
from ne_demand.training.tracking import REGISTERED_MODEL, load_production
from ne_demand.validation.schemas import DataValidationError, validate_load, validate_weather

log = logging.getLogger(__name__)

# Features that must never be missing; lag features may be NaN by design.
REQUIRED_FEATURES = ["hour", "weekday", "lead_hours", "last_known_load", "temp_mean", *TEMP_COLUMNS]


def forecast_path(root: str, day: date, issued_at: datetime) -> str:
    stamp = issued_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{root.rstrip('/')}/forecasts/date={day.isoformat()}/issued_at={stamp}.parquet"


PUBLISHED = "published/forecasts.parquet"


def publish(root: str, out: pd.DataFrame) -> None:
    """Append to the single table the dashboard reads (one request, fast page loads)."""
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/{PUBLISHED}")
    existing = pd.DataFrame()
    if fs.exists(path):
        with fs.open(path, "rb") as f:
            existing = pd.read_parquet(f)
    merged = pd.concat([existing, out], ignore_index=True).drop_duplicates(
        ["time", "issued_at"], keep="last"
    )
    fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(path, "wb") as f:
        merged.to_parquet(f, index=False)


def forecast_exists(root: str, day: date) -> bool:
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/forecasts/date={day.isoformat()}")
    return fs.exists(path) and bool(fs.ls(path))


def live_temps(root: str, now: datetime) -> pd.DataFrame:
    """Fetch the current weather forecast, archive it as issued, return it wide by station."""
    raw = weather.fetch_forecast()
    write_raw(raw, root, "weather_forecast_live", now.date(), now)
    raw = raw.assign(fetched_at=pd.Timestamp(now))
    return weather_hourly(raw, column="temperature_2m")


def run_forecast(
    root: str,
    target_day: date | None = None,
    now: datetime | None = None,
    temps: pd.DataFrame | None = None,
) -> pd.DataFrame:
    now = now or datetime.now(UTC)
    issue = pd.Timestamp(now)
    target_day = target_day or (issue.tz_convert(LOCAL_TZ).date() + timedelta(days=1))
    idx = target_hours(target_day)
    if issue >= idx[0]:
        log.warning("forecast for %s issued after the day started (%s)", target_day, issue)

    booster, meta = load_production()
    lags = meta["config"]["lag_hours"]

    load_df = read_processed(root, "load_hourly")
    cutoff = issue.floor("h")
    window_start = cutoff - pd.Timedelta(hours=max(lags) + 24)
    recent = load_df[(load_df["time"] >= window_start) & (load_df["time"] < cutoff)]
    validate_load(recent, window_start, cutoff)

    temps = temps if temps is not None else live_temps(root, now)
    target_temps = temps[temps["time"].isin(idx)]
    validate_weather(target_temps, idx[0], idx[-1] + pd.Timedelta(hours=1))

    load = recent.set_index("time")["load_mw"]
    feats = build_features(load, target_temps.set_index("time"), idx, issue, lags)
    missing = feats[REQUIRED_FEATURES].isna().sum()
    if missing.any():
        raise DataValidationError(
            f"features: required values missing {missing[missing > 0].to_dict()}"
        )

    out = pd.DataFrame(
        {
            "time": idx,
            "forecast_mw": booster.predict(feats[meta["features"]]),
            "naive_mw": same_hour_last_week(load, idx).to_numpy(),
            "model_version": f"{REGISTERED_MODEL}/v{meta['registry_version']}",
            "model_id": meta["version"],
            "git_commit": meta["git_commit"],
            "issued_at": issue,
            "target_day": target_day,
        }
    )
    path = forecast_path(root, target_day, now)
    fs, fs_path = fsspec.core.url_to_fs(path)
    fs.makedirs(fs_path.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(fs_path, "wb") as f:
        out.to_parquet(f, index=False)
    publish(root, out)
    log.info(
        "published %d-hour forecast for %s with %s -> %s",
        len(out),
        target_day,
        meta["version"],
        path,
    )
    return out
