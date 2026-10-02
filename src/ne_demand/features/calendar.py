"""Calendar features derived from a UTC hourly index.

Timestamps are stored in UTC; demand follows local clock time, so hour and
weekday are computed in America/New_York. This keeps 23- and 25-hour DST days
correct without any special-casing.
"""

from __future__ import annotations

import holidays
import pandas as pd

from ne_demand.config import LOCAL_TZ


def calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    if index.tz is None:
        raise ValueError("index must be timezone-aware UTC")
    local = index.tz_convert(LOCAL_TZ)
    years = range(local.year.min(), local.year.max() + 1)
    us_holidays = holidays.country_holidays("US", years=years)
    return pd.DataFrame(
        {
            "hour": local.hour,
            "weekday": local.weekday,
            "month": local.month,
            "is_weekend": local.weekday >= 5,
            "is_holiday": [d in us_holidays for d in local.date],
        },
        index=index,
    )
