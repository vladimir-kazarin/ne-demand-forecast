"""End-to-end smoke test: processed tables -> train -> forecast, on synthetic data."""

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from ne_demand.forecast.batch import run_forecast
from ne_demand.training.tracking import load_production
from ne_demand.training.train import train
from ne_demand.validation.schemas import DataValidationError

pytestmark = pytest.mark.smoke

ISSUE = datetime(2026, 3, 19, 14, 30, tzinfo=UTC)  # 10:30 EDT on Mar 19
TARGET = date(2026, 3, 20)


def _write(root: Path, load: pd.DataFrame, weather: pd.DataFrame) -> None:
    (root / "processed").mkdir(parents=True, exist_ok=True)
    load.to_parquet(root / "processed" / "load_hourly.parquet", index=False)
    weather.to_parquet(root / "processed" / "weather_hourly.parquet", index=False)


def _forecasts(root: Path) -> list[Path]:
    return list((root / "forecasts").rglob("*.parquet")) if (root / "forecasts").exists() else []


@pytest.fixture
def trained_root(tmp_path, tables, small_config):
    load, weather = tables
    _write(tmp_path, load[load["time"] < pd.Timestamp(ISSUE).floor("h")], weather)
    train(small_config, str(tmp_path), end_day=date(2026, 3, 18))
    return tmp_path


def test_training_beats_naive_and_records_lineage(trained_root):
    _, meta = load_production()
    m = meta["metrics"]
    assert m["holdout_mape"] < m["naive_holdout_mape"]
    assert meta["git_commit"]
    assert meta["data_window"]["holdout_end"] == "2026-03-18"


def test_retraining_same_config_reproduces_metrics(trained_root, small_config):
    _, first = load_production()
    second = train(small_config, str(trained_root), end_day=date(2026, 3, 18))
    assert second["metrics"]["holdout_mape"] == pytest.approx(first["metrics"]["holdout_mape"])


def test_forecast_published_for_next_day(trained_root, tables):
    _, weather = tables
    out = run_forecast(str(trained_root), TARGET, ISSUE, temps=weather)
    assert len(out) == 24
    assert out["forecast_mw"].between(5_000, 25_000).all()
    assert (out["model_version"] == "ne-demand-lightgbm/v1").all()
    assert len(_forecasts(trained_root)) == 1
    published = pd.read_parquet(trained_root / "published" / "forecasts.parquet")
    assert len(published) == 24


def test_broken_column_fails_and_publishes_nothing(trained_root, tables):
    load, weather = tables
    broken = load[load["time"] < pd.Timestamp(ISSUE).floor("h")].assign(
        load_mw=lambda d: d["load_mw"] / 1000
    )
    broken.to_parquet(trained_root / "processed" / "load_hourly.parquet", index=False)

    with pytest.raises(DataValidationError, match="load_hourly"):
        run_forecast(str(trained_root), TARGET, ISSUE, temps=weather)
    assert _forecasts(trained_root) == []


def test_missing_weather_fails_and_publishes_nothing(trained_root, tables):
    _, weather = tables
    with pytest.raises(DataValidationError, match="weather_hourly"):
        run_forecast(str(trained_root), TARGET, ISSUE, temps=weather.iloc[:-30])
    assert _forecasts(trained_root) == []
