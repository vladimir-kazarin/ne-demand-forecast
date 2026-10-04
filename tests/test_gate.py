"""Evaluation gate and rollback against a throwaway registry."""

from datetime import date

import pytest
from mlflow import MlflowClient

from ne_demand.config import TrainConfig, TrainingWindow
from ne_demand.evaluation.events import read_events
from ne_demand.evaluation.gate import rollback, run_gate
from ne_demand.training import tracking
from ne_demand.training.train import train

pytestmark = pytest.mark.smoke


def _config(name: str, **lightgbm) -> TrainConfig:
    return TrainConfig(
        name=name,
        window=TrainingWindow(lookback_days=40, holdout_days=7),
        lightgbm={"objective": "regression_l1", "num_leaves": 15} | lightgbm,
    )


GOOD = _config("good", n_estimators=80)
DEGRADED = _config("degraded", n_estimators=2, learning_rate=0.01)  # barely fits


@pytest.fixture
def root(tmp_path, tables):
    load, weather = tables
    (tmp_path / "processed").mkdir()
    load.to_parquet(tmp_path / "processed" / "load_hourly.parquet", index=False)
    weather.to_parquet(tmp_path / "processed" / "weather_hourly.parquet", index=False)
    return str(tmp_path)


def test_degraded_candidate_is_rejected(root):
    train(GOOD, root, end_day=date(2026, 3, 17))  # v1, production
    train(DEGRADED, root, end_day=date(2026, 3, 18))  # v2, candidate

    r = run_gate(root)
    assert r.decision == "rejected"
    assert tracking.production_version() == "1"
    tags = tracking.version_tags("2")
    assert tags["gate_decision"] == "rejected"
    assert "naive" in tags["gate_reason"] or "not 2% better" in tags["gate_reason"]
    assert read_events(root)["event"].tolist()[-1] == "rejected"


def test_better_candidate_is_promoted(root):
    train(DEGRADED, root, end_day=date(2026, 3, 17))  # v1 promoted as first model
    train(GOOD, root, end_day=date(2026, 3, 18))

    r = run_gate(root)
    assert r.decision == "promoted", r.reason
    assert r.candidate_mape < r.production_mape * 0.98
    assert tracking.production_version() == "2"
    assert tracking.version_tags("2")["previous_production"] == "1"


def test_equal_model_is_rejected_by_margin(root):
    train(GOOD, root, end_day=date(2026, 3, 18))
    train(GOOD, root, end_day=date(2026, 3, 18))  # identical data and config

    r = run_gate(root)
    assert r.decision == "rejected"
    assert "not 2% better" in r.reason


def test_both_models_scored_on_the_same_unseen_days(root):
    train(GOOD, root, end_day=date(2026, 3, 17))
    meta = train(GOOD, root, end_day=date(2026, 3, 18))
    r = run_gate(root)
    assert (r.holdout_start, r.holdout_end) == (
        meta["data_window"]["holdout_start"],
        meta["data_window"]["holdout_end"],
    )
    assert r.holdout_start > meta["data_window"]["train_end"]


def test_rollback_returns_previous_version_and_is_logged(root):
    train(DEGRADED, root, end_day=date(2026, 3, 17))
    train(GOOD, root, end_day=date(2026, 3, 18))
    run_gate(root)  # promotes v2

    assert rollback(root, "drill") == ("2", "1")
    assert tracking.production_version() == "1"
    mv = MlflowClient().get_model_version(tracking.REGISTERED_MODEL, "1")
    assert mv.tags["promotion_reason"] == "rollback from v2: drill"
    last = read_events(root).iloc[-1]
    assert (last["event"], last["version"], last["from_version"]) == ("rolled_back", "1", "2")


def test_rollback_without_previous_version_fails(root):
    train(GOOD, root, end_day=date(2026, 3, 18))
    with pytest.raises(LookupError, match="no previous production"):
        rollback(root, "nothing to go back to")


def test_event_log_records_every_registration(root):
    train(GOOD, root, end_day=date(2026, 3, 17))
    train(DEGRADED, root, end_day=date(2026, 3, 18))
    run_gate(root)
    assert read_events(root)["event"].tolist() == [
        "registered",
        "promoted",
        "registered",
        "rejected",
    ]
