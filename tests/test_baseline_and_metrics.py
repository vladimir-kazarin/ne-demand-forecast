import pandas as pd
import pytest

from ne_demand.evaluation.metrics import mape
from ne_demand.forecast.baseline import same_hour_last_week


def test_naive_baseline_uses_value_one_week_earlier():
    idx = pd.date_range("2026-01-01", periods=24 * 9, freq="h", tz="UTC")
    load = pd.Series(range(len(idx)), index=idx, dtype=float)
    target = idx[-24:]
    pred = same_hour_last_week(load, target)
    assert (pred.to_numpy() == load.loc[target - pd.Timedelta(hours=168)].to_numpy()).all()


def test_mape():
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    assert mape(pd.Series([100.0, 200.0], idx), pd.Series([110.0, 180.0], idx)) == pytest.approx(
        10.0
    )


def test_mape_rejects_no_overlap():
    a = pd.Series([1.0], pd.DatetimeIndex(["2026-01-01"], tz="UTC"))
    f = pd.Series([1.0], pd.DatetimeIndex(["2026-01-02"], tz="UTC"))
    with pytest.raises(ValueError):
        mape(a, f)
