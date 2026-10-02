"""Historical backfill and the live as-issued archive.

Backfill is resumable: a day whose raw partition already exists is skipped,
so re-running a range never creates duplicates.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from ne_demand.ingestion import isone, weather
from ne_demand.ingestion.storage import partition_exists, write_raw

log = logging.getLogger(__name__)

SOURCES = ("isone_load", "isone_load_forecast", "weather_previous_runs")
ARCHIVE_SOURCES = ("isone_load_forecast_live", "weather_forecast_live")


def _days(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _backfill_daily(
    root: str, source: str, fetch: Callable[[date], pd.DataFrame], days: list[date], workers: int
) -> int:
    todo = [d for d in days if not partition_exists(root, source, d)]
    log.info("%s: %d of %d days to fetch", source, len(todo), len(days))
    written = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, d): d for d in todo}
        for fut in as_completed(futures):
            day = futures[fut]
            try:
                write_raw(fut.result(), root, source, day, datetime.now(UTC))
                written += 1
            except Exception:
                log.exception("%s %s failed; re-run to retry", source, day)
    return written


def _backfill_weather(root: str, days: list[date]) -> int:
    source = "weather_previous_runs"
    todo = [d for d in days if not partition_exists(root, source, d)]
    log.info("%s: %d of %d days to fetch", source, len(todo), len(days))
    written = 0
    # One request per station per ~month, then split into daily partitions.
    for i in range(0, len(todo), 31):
        chunk = todo[i : i + 31]
        df = weather.fetch_previous_runs(chunk[0], chunk[-1])
        fetched_at = datetime.now(UTC)
        for day in chunk:
            part = df[df["time"].dt.date == day]
            if not part.empty:
                write_raw(part, root, source, day, fetched_at)
                written += 1
    return written


def backfill(root: str, source: str, start: date, end: date, workers: int = 4) -> int:
    days = list(_days(start, end))
    if source == "isone_load":
        return _backfill_daily(root, source, isone.fetch_load, days, workers)
    if source == "isone_load_forecast":
        return _backfill_daily(root, source, isone.fetch_load_forecast, days, workers)
    if source == "weather_previous_runs":
        return _backfill_weather(root, days)
    raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")


def archive(root: str) -> list[str]:
    """Snapshot the currently published forecasts exactly as issued.

    Partitioned by the UTC date of capture; every run adds a new file.
    """
    now = datetime.now(UTC)
    today_local = pd.Timestamp(now).tz_convert("America/New_York").date()
    return [
        write_raw(
            isone.fetch_load_forecast(today_local), root, ARCHIVE_SOURCES[0], now.date(), now
        ),
        write_raw(weather.fetch_forecast(), root, ARCHIVE_SOURCES[1], now.date(), now),
    ]
