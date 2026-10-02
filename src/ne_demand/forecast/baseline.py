"""Naive benchmark: demand at the same hour one week earlier."""

from __future__ import annotations

import pandas as pd


def same_hour_last_week(load: pd.Series, target_index: pd.DatetimeIndex) -> pd.Series:
    values = load.reindex(target_index - pd.Timedelta(hours=168)).to_numpy()
    return pd.Series(values, index=target_index, name="naive_forecast")
