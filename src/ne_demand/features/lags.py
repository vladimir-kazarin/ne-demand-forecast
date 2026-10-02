"""Lagged-load features that only use data known at the forecast issue time."""

from __future__ import annotations

import pandas as pd


def known_at(load: pd.Series, issue_time: pd.Timestamp) -> pd.Series:
    """Hours that were complete at issue_time (an hour starting at t ends at t+1h)."""
    return load[load.index + pd.Timedelta(hours=1) <= issue_time]


def lag_features(
    load: pd.Series, target_index: pd.DatetimeIndex, lags: list[int], issue_time: pd.Timestamp
) -> pd.DataFrame:
    """Return load lagged by each hour count, for every target hour.

    Any lagged value whose source hour was not complete at `issue_time` is
    unknown at prediction time and is set to NaN rather than leaked.
    """
    known = known_at(load, issue_time)
    out = {}
    for lag in lags:
        source = target_index - pd.Timedelta(hours=lag)
        out[f"load_lag_{lag}h"] = known.reindex(source).to_numpy()
    return pd.DataFrame(out, index=target_index)
