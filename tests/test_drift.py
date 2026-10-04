from datetime import date

import numpy as np
import pandas as pd
import pytest

from ne_demand.features.build import TEMP_COLUMNS
from ne_demand.monitoring.drift import (
    check_drift,
    inject_shift,
    psi,
    psi_status,
    seasonal_reference_days,
)

rng = np.random.default_rng(0)
OFFSETS = {
    "temp_boston": -0.5,
    "temp_hartford": 1.0,
    "temp_providence": 0.2,
    "temp_manchester": -0.7,
}


def _features(n: int, base: float = 12.0) -> pd.DataFrame:
    weather = rng.normal(base, 5, n)  # shared regional weather
    df = pd.DataFrame({c: weather + off + rng.normal(0, 0.6, n) for c, off in OFFSETS.items()})
    df["temp_mean"] = df[TEMP_COLUMNS].mean(axis=1)
    df["load_lag_48h"] = rng.normal(13_000, 1_500, n)
    df["load_lag_168h"] = rng.normal(13_000, 1_500, n)
    return df


def _range(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    return df[TEMP_COLUMNS].min(), df[TEMP_COLUMNS].max()


TRAINING = _features(17_000)


def test_psi_near_zero_for_same_distribution():
    assert psi(rng.normal(0, 1, 5_000), rng.normal(0, 1, 5_000)) < 0.02


def test_psi_large_for_shifted_distribution():
    assert psi(rng.normal(0, 1, 5_000), rng.normal(1.5, 1, 5_000)) > 0.25


@pytest.mark.parametrize("value, expected", [(0.05, "stable"), (0.1, "watch"), (0.3, "drift")])
def test_psi_status_thresholds(value, expected):
    assert psi_status(value) == expected


def test_warmer_week_is_not_an_alert():
    """Different weather from last year is the model's job, not a data fault."""
    r = check_drift(_features(840), _features(168, base=17.0), _range(TRAINING))
    assert not r.drifted, r.alerts


def test_one_station_shifted_fires_consistency_alert():
    cur = inject_shift(_features(168), {"temp_boston": 8.0})
    r = check_drift(_features(840), cur, _range(TRAINING))
    assert r.drifted
    assert "boston" in r.alerts[0] and "data fault" in r.alerts[0]
    assert r.spread_shift_c["boston"] > 5


def test_temperatures_beyond_training_range_fire_extrapolation_alert():
    cur = _features(168, base=12.0)
    cur[TEMP_COLUMNS] = cur[TEMP_COLUMNS] - 40  # far colder than anything in training
    cur["temp_mean"] = cur[TEMP_COLUMNS].mean(axis=1)
    r = check_drift(_features(840), cur, _range(TRAINING))
    assert r.out_of_range_share > 0.9
    assert any("extrapolating" in a for a in r.alerts)


def test_context_table_reports_every_feature():
    r = check_drift(_features(840), _features(168), _range(TRAINING))
    assert set(r.context["feature"]) == {
        *TEMP_COLUMNS,
        "temp_mean",
        "load_lag_48h",
        "load_lag_168h",
    }


def test_seasonal_reference_is_last_year_same_weekdays():
    cur = [date(2026, 10, d) for d in range(1, 8)]
    ref = seasonal_reference_days(cur, pad_days=14)
    assert len(ref) == 7 + 28
    assert ref[0] == date(2025, 9, 18) and ref[-1] == date(2025, 10, 22)
    assert ref[14].weekday() == cur[0].weekday()
