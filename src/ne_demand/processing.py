"""Turn raw partitions into hourly processed tables.

Processed tables are rebuilt from raw and upserted by key, latest fetch wins,
so re-processing any range is idempotent:

    {root}/processed/load_hourly.parquet       time, load_mw
    {root}/processed/weather_hourly.parquet    time, temp_<station>... (day-ahead forecast °C)
    {root}/processed/iso_forecast.parquet      time, forecast_time, iso_forecast_mw, vintage
"""

from __future__ import annotations

import logging
from datetime import date

import fsspec
import pandas as pd

from ne_demand.config import LOCAL_TZ
from ne_demand.ingestion.readers import read_raw

log = logging.getLogger(__name__)

INTERVALS_PER_HOUR = 12


def processed_path(root: str, table: str) -> str:
    return f"{root.rstrip('/')}/processed/{table}.parquet"


def read_processed(root: str, table: str) -> pd.DataFrame:
    fs, path = fsspec.core.url_to_fs(processed_path(root, table))
    if not fs.exists(path):
        return pd.DataFrame()
    with fs.open(path, "rb") as f:
        return pd.read_parquet(f)


def _upsert(root: str, table: str, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    merged = pd.concat([read_processed(root, table), new], ignore_index=True)
    merged = merged.drop_duplicates(keys, keep="last").sort_values(keys).reset_index(drop=True)
    fs, path = fsspec.core.url_to_fs(processed_path(root, table))
    fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(path, "wb") as f:
        merged.to_parquet(f, index=False)
    return merged


def load_hourly(raw: pd.DataFrame) -> pd.DataFrame:
    """5-minute load to hourly mean MW. Hours missing any interval are dropped,
    so gaps surface in validation instead of as biased averages."""
    five_min = (
        raw.sort_values("fetched_at")
        .assign(start=lambda d: pd.to_datetime(d["Interval Start"], utc=True))
        .drop_duplicates("start", keep="last")
    )
    hourly = five_min.groupby(five_min["start"].dt.floor("h"))["Load"].agg(["mean", "count"])
    complete = hourly[hourly["count"] == INTERVALS_PER_HOUR]
    return pd.DataFrame({"time": complete.index, "load_mw": complete["mean"].to_numpy()})


def weather_hourly(raw: pd.DataFrame, column: str = "temperature_2m_previous_day1") -> pd.DataFrame:
    """Day-ahead forecast temperature, one column per station."""
    latest = raw.sort_values("fetched_at").drop_duplicates(["time", "station"], keep="last")
    # pivot (not pivot_table) so a duplicate (time, station) raises instead of being averaged.
    wide = latest.pivot(index="time", columns="station", values=column)  # noqa: PD010
    wide = wide.add_prefix("temp_")
    wide.columns.name = None
    return wide.reset_index()


def iso_forecast(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(raw["Interval Start"], utc=True),
            "forecast_time": pd.to_datetime(raw["Forecast Time"], utc=True),
            "iso_forecast_mw": raw["Load Forecast"].astype(float),
        }
    )
    target_day = df["time"].dt.tz_convert(LOCAL_TZ).dt.date
    issued_day = df["forecast_time"].dt.tz_convert(LOCAL_TZ).dt.date
    df["vintage"] = (target_day > issued_day).map({True: "day_ahead", False: "same_day"})
    return df.drop_duplicates(["time", "forecast_time"])


def process(root: str, start: date, end: date) -> dict[str, int]:
    """Rebuild processed rows from raw partitions dated start..end."""
    counts = {}
    load_raw = read_raw(root, "isone_load", start, end)
    if not load_raw.empty:
        counts["load_hourly"] = len(_upsert(root, "load_hourly", load_hourly(load_raw), ["time"]))

    weather_raw = read_raw(root, "weather_previous_runs", start, end)
    if not weather_raw.empty:
        counts["weather_hourly"] = len(
            _upsert(root, "weather_hourly", weather_hourly(weather_raw), ["time"])
        )

    iso_raw = pd.concat(
        [
            read_raw(root, "isone_load_forecast", start, end),
            read_raw(root, "isone_load_forecast_live", start, end),
        ],
        ignore_index=True,
    )
    if not iso_raw.empty:
        counts["iso_forecast"] = len(
            _upsert(root, "iso_forecast", iso_forecast(iso_raw), ["time", "forecast_time"])
        )
    log.info("processed %s..%s: %s", start, end, counts)
    return counts
