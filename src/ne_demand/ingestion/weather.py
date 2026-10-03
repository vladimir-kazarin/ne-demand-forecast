"""Open-Meteo forecast temperature for the four New England stations.

Training must use weather as it was forecast, not as observed. Two endpoints:

- Previous Runs API (backfill): `temperature_2m_previous_dayN` is the value
  forecast N days before each hour. Full coverage from 2022 onward.
- Forecast API (live archive): the current forecast, stored as issued.
"""

from __future__ import annotations

from datetime import date

import httpx
import pandas as pd

from ne_demand.config import WEATHER_STATIONS
from ne_demand.ingestion.retry import retrying

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_VARS = [
    "temperature_2m",
    "temperature_2m_previous_day1",
    "temperature_2m_previous_day2",
]


@retrying
def _get(url: str, params: dict) -> dict:
    resp = httpx.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _frame(payload: dict, station: str) -> pd.DataFrame:
    df = pd.DataFrame(payload["hourly"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df.insert(0, "station", station)
    df["latitude"], df["longitude"] = payload["latitude"], payload["longitude"]
    return df


def fetch_previous_runs(start: date, end: date) -> pd.DataFrame:
    frames = []
    for station, (lat, lon) in WEATHER_STATIONS.items():
        payload = _get(
            PREVIOUS_RUNS_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": ",".join(PREVIOUS_RUNS_VARS),
                "timezone": "GMT",
            },
        )
        frames.append(_frame(payload, station))
    return pd.concat(frames, ignore_index=True)


def fetch_forecast(forecast_days: int = 4) -> pd.DataFrame:
    # Days are UTC. A local (ET) target day ends 4-5 hours into the next UTC day, so a
    # forecast issued late, or for two days out, needs the 4th UTC day to cover its evening.
    frames = []
    for station, (lat, lon) in WEATHER_STATIONS.items():
        payload = _get(
            FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "forecast_days": forecast_days,
                "timezone": "GMT",
            },
        )
        frames.append(_frame(payload, station))
    return pd.concat(frames, ignore_index=True)
