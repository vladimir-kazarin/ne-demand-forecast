"""One feature path for training and serving.

`build_features` makes the features for one target day as seen at one issue
time. Serving calls it once with the real issue time; training calls it for
every historical day with that day's scheduled issue time, so the model never
trains on information it would not have live.
"""

from __future__ import annotations

from datetime import date, time, timedelta

import pandas as pd

from ne_demand.config import LOCAL_TZ, WEATHER_STATIONS
from ne_demand.features.calendar import calendar_features
from ne_demand.features.lags import known_at, lag_features

TEMP_COLUMNS = [f"temp_{s}" for s in WEATHER_STATIONS]


def target_hours(day: date) -> pd.DatetimeIndex:
    """UTC start of every local hour in `day`: 23, 24, or 25 of them."""
    start = pd.Timestamp(day, tz=LOCAL_TZ)
    end = pd.Timestamp(day + timedelta(days=1), tz=LOCAL_TZ)
    return pd.date_range(start, end, freq="h", inclusive="left").tz_convert("UTC")


def scheduled_issue_time(day: date, issue_local: time) -> pd.Timestamp:
    """When the forecast for `day` is issued: `issue_local` on the previous local day."""
    local = pd.Timestamp.combine(day - timedelta(days=1), issue_local).tz_localize(LOCAL_TZ)
    return local.tz_convert("UTC")


def build_features(
    load: pd.Series,
    temps: pd.DataFrame,
    target_index: pd.DatetimeIndex,
    issue_time: pd.Timestamp,
    lags: list[int],
) -> pd.DataFrame:
    """Features for `target_index`.

    load:  hourly MW indexed by UTC hour start (anything after issue_time is ignored)
    temps: forecast temperature per station indexed by UTC hour, as available at issue_time
    """
    known = known_at(load, issue_time)
    t = temps.reindex(target_index)[TEMP_COLUMNS]
    feats = pd.concat(
        [
            calendar_features(target_index),
            lag_features(load, target_index, lags, issue_time),
            t,
        ],
        axis=1,
    )
    feats["temp_mean"] = t.mean(axis=1)
    feats["lead_hours"] = (target_index - issue_time) / pd.Timedelta(hours=1)
    feats["last_known_load"] = known.iloc[-1] if len(known) else float("nan")
    return feats


def training_frame(
    load: pd.Series,
    temps: pd.DataFrame,
    days: list[date],
    issue_local: time,
    lags: list[int],
) -> pd.DataFrame:
    """Features plus target `load_mw` for each day, each built as of its own issue time."""
    frames = []
    for day in days:
        idx = target_hours(day)
        issue = scheduled_issue_time(day, issue_local)
        f = build_features(load, temps, idx, issue, lags)
        f["load_mw"] = load.reindex(idx).to_numpy()
        f["target_day"] = day
        frames.append(f)
    return pd.concat(frames).dropna(subset=["load_mw"])
