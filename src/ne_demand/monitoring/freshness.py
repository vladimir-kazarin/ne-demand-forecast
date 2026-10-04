"""Freshness: catches jobs that never ran, which failure alerts cannot see."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import fsspec
import pandas as pd

from ne_demand.config import LOCAL_TZ
from ne_demand.processing import read_processed

LOAD_MAX_AGE = timedelta(hours=3)
FORECAST_DUE_LOCAL = time(12, 0)


def check_freshness(root: str, now: datetime) -> dict[str, str | None]:
    checks: dict[str, str | None] = {}

    load = read_processed(root, "load_hourly")
    if load.empty:
        checks["data_freshness"] = "no processed demand data found"
    else:
        age = pd.Timestamp(now) - (load["time"].max() + pd.Timedelta(hours=1))
        checks["data_freshness"] = (
            f"latest demand data is {age.total_seconds() / 3600:.1f} h old "
            f"(limit {LOAD_MAX_AGE.total_seconds() / 3600:.0f} h): ingestion may have stopped"
            if age > LOAD_MAX_AGE
            else None
        )

    local = pd.Timestamp(now).tz_convert(LOCAL_TZ)
    tomorrow = local.date() + timedelta(days=1)
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/published/forecasts.parquet")
    days = set()
    if fs.exists(path):
        with fs.open(path, "rb") as f:
            days = set(pd.read_parquet(f, columns=["target_day"])["target_day"])
    checks["forecast_published"] = (
        f"no forecast for {tomorrow} by {FORECAST_DUE_LOCAL:%H:%M} ET"
        if local.time() >= FORECAST_DUE_LOCAL and tomorrow not in days
        else None
    )
    return checks
