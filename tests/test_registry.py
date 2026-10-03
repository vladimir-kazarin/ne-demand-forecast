from datetime import date

import pytest
from mlflow import MlflowClient

from ne_demand.training import tracking
from ne_demand.training.train import train

pytestmark = pytest.mark.smoke


@pytest.fixture
def root(tmp_path, tables):
    load, weather = tables
    (tmp_path / "processed").mkdir()
    load.to_parquet(tmp_path / "processed" / "load_hourly.parquet", index=False)
    weather.to_parquet(tmp_path / "processed" / "weather_hourly.parquet", index=False)
    return str(tmp_path)


def _alias(name: str) -> str:
    return str(MlflowClient().get_model_version_by_alias(tracking.REGISTERED_MODEL, name).version)


def test_registry_alone_traces_production_to_data_and_commit(root, small_config):
    meta = train(small_config, root, end_day=date(2026, 3, 18))
    mv = MlflowClient().get_model_version_by_alias(tracking.REGISTERED_MODEL, "production")
    assert mv.tags["git_commit"] == meta["git_commit"]
    assert mv.tags["data_hash"] == meta["data_hash"]
    assert mv.tags["data.holdout_end"] == "2026-03-18"
    assert mv.tags["data.train_start"] == meta["data_window"]["train_start"]
    assert mv.tags["promotion_reason"].startswith("first model")
    run = MlflowClient().get_run(mv.tags["run_id"])
    assert run.data.metrics["holdout_mape"] == pytest.approx(meta["metrics"]["holdout_mape"])
    assert run.data.params["window.lookback_days"] == "40"


def test_new_training_becomes_candidate_not_production(root, small_config):
    train(small_config, root, end_day=date(2026, 3, 17))
    train(small_config, root, end_day=date(2026, 3, 18))
    assert _alias("production") == "1"
    assert _alias("candidate") == "2"


def test_promote_moves_production_and_records_reason(root, small_config):
    train(small_config, root, end_day=date(2026, 3, 17))
    train(small_config, root, end_day=date(2026, 3, 18))
    tracking.promote("2", "manual: newer data window")
    mv = MlflowClient().get_model_version(tracking.REGISTERED_MODEL, "2")
    assert _alias("production") == "2"
    assert mv.tags["previous_production"] == "1"
    assert mv.tags["promotion_reason"] == "manual: newer data window"


def test_same_data_same_hash(tables):
    load, _ = tables
    assert tracking.data_hash(load) == tracking.data_hash(load.copy())
    assert tracking.data_hash(load) != tracking.data_hash(load.assign(load_mw=load["load_mw"] + 1))


def test_forecast_without_production_model_fails_clearly(root):
    with pytest.raises(LookupError, match="no 'production' alias"):
        tracking.load_production()
