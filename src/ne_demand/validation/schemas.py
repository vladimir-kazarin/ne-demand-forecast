"""Data checks run before training and before forecasting.

Every failure raises DataValidationError with a message naming the table,
the check, and example offending rows, so a broken run is diagnosable from
the job log alone.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

from ne_demand.config import WEATHER_STATIONS


class DataValidationError(Exception):
    pass


_utc_hour = pa.Column(
    pd.DatetimeTZDtype(tz="UTC"),
    checks=pa.Check(lambda s: (s == s.dt.floor("h")).all(), error="timestamps not on the hour"),
    unique=True,
    nullable=False,
)

LOAD_HOURLY = pa.DataFrameSchema(
    {
        "time": _utc_hour,
        # New England system load has ranged ~6-28 GW; wider bounds catch unit errors and junk.
        "load_mw": pa.Column(float, pa.Check.in_range(3_000, 35_000), nullable=False),
    },
    strict=True,
    name="load_hourly",
)

WEATHER_HOURLY = pa.DataFrameSchema(
    {"time": _utc_hour}
    | {
        f"temp_{s}": pa.Column(float, pa.Check.in_range(-45, 50), nullable=False)
        for s in WEATHER_STATIONS
    },
    strict=True,
    name="weather_hourly",
)


def _validate(schema: pa.DataFrameSchema, df: pd.DataFrame) -> pd.DataFrame:
    try:
        return schema.validate(df, lazy=True)
    except SchemaErrors as e:
        cases = e.failure_cases[["column", "check", "failure_case"]].head(10)
        raise DataValidationError(
            f"{schema.name}: {len(e.failure_cases)} failed checks\n{cases.to_string(index=False)}"
        ) from None


def require_hours(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, name: str) -> None:
    """Every hour in [start, end) must be present."""
    expected = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")
    missing = expected.difference(pd.DatetimeIndex(df["time"]))
    if len(missing):
        sample = ", ".join(t.isoformat() for t in missing[:5])
        raise DataValidationError(
            f"{name}: {len(missing)} missing hours between {start} and {end}; first: {sample}"
        )


def validate_load(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = _validate(LOAD_HOURLY, df)
    require_hours(df, start, end, "load_hourly")
    return df


def validate_weather(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = _validate(WEATHER_HOURLY, df)
    require_hours(df, start, end, "weather_hourly")
    return df
