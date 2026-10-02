"""ISO New England public data via gridstatus (no ISO Express login required).

- Load: 5-minute system load. Aggregation to hourly happens in processing.
- Load forecast: the file for day D holds D's forecast and, once published,
  D+1's. Historical files keep only the same-day vintage, so the day-ahead
  vintage can only be captured by archiving it live (see `archive`).
"""

from __future__ import annotations

from datetime import date

import gridstatus
import pandas as pd

from ne_demand.ingestion.retry import retrying


@retrying
def fetch_load(day: date) -> pd.DataFrame:
    return gridstatus.ISONE().get_load(day.isoformat())


@retrying
def fetch_load_forecast(day: date) -> pd.DataFrame:
    return gridstatus.ISONE().get_load_forecast(day.isoformat())
