import numpy as np
import pandas as pd
import pytest

from ne_demand.validation.schemas import DataValidationError, validate_load, validate_weather


def _bounds(df):
    return df["time"].min(), df["time"].max() + pd.Timedelta(hours=1)


def test_clean_tables_pass(tables):
    load, weather = tables
    validate_load(load, *_bounds(load))
    validate_weather(weather, *_bounds(weather))


@pytest.mark.parametrize(
    "corrupt, expected",
    [
        (lambda d: d.assign(load_mw=d["load_mw"] / 1000), "in_range"),  # MW reported as GW
        (lambda d: d.assign(load_mw=np.where(d.index == 5, np.nan, d["load_mw"])), "not_nullable"),
        (lambda d: d.assign(load_mw=d["load_mw"].astype(str)), "dtype"),
        (lambda d: d.rename(columns={"load_mw": "load"}), "column_in_dataframe"),
        (lambda d: pd.concat([d, d.iloc[[3]]]), "field_uniqueness"),
    ],
)
def test_corrupted_load_fails_with_named_check(tables, corrupt, expected):
    load, _ = tables
    with pytest.raises(DataValidationError, match="load_hourly") as exc:
        validate_load(corrupt(load), *_bounds(load))
    assert expected in str(exc.value)


def test_missing_hours_reported(tables):
    load, _ = tables
    gappy = load.drop(index=range(100, 103))
    with pytest.raises(DataValidationError, match="3 missing hours"):
        validate_load(gappy, *_bounds(load))


def test_out_of_range_temperature_fails(tables):
    _, weather = tables
    bad = weather.assign(temp_boston=weather["temp_boston"] + 273.15)  # Kelvin
    with pytest.raises(DataValidationError, match="temp_boston"):
        validate_weather(bad, *_bounds(weather))
