from datetime import date

import numpy as np
import pandas as pd
import pytest

from ne_demand.config import WEATHER_STATIONS, TrainConfig, TrainingWindow


def synthetic_tables(days: int = 60, end: date = date(2026, 3, 20), seed: int = 0):
    """Hourly load driven by hour-of-day and temperature, plus matching temps."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(
        pd.Timestamp(end, tz="America/New_York") - pd.Timedelta(days=days),
        pd.Timestamp(end, tz="America/New_York") + pd.Timedelta(days=2),
        freq="h",
        inclusive="left",
    ).tz_convert("UTC")
    local_hour = idx.tz_convert("America/New_York").hour.to_numpy()
    temp = 5 + 8 * np.sin(2 * np.pi * (local_hour - 9) / 24) + rng.normal(0, 1, len(idx))
    load = 13_000 + 2_500 * np.sin(2 * np.pi * (local_hour - 6) / 24) - 120 * temp
    load = load + rng.normal(0, 150, len(idx))
    load_df = pd.DataFrame({"time": idx, "load_mw": load})
    weather_df = pd.DataFrame({"time": idx} | {f"temp_{s}": temp for s in WEATHER_STATIONS})
    return load_df, weather_df


@pytest.fixture
def tables():
    return synthetic_tables()


@pytest.fixture
def small_config() -> TrainConfig:
    return TrainConfig(
        name="test",
        window=TrainingWindow(lookback_days=40, holdout_days=7),
        lightgbm={"n_estimators": 50, "num_leaves": 15, "objective": "regression_l1"},
    )


@pytest.fixture(autouse=True)
def local_mlflow(tmp_path, monkeypatch):
    """Every test gets its own throwaway MLflow tracking store and registry."""
    import mlflow

    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    mlflow.set_tracking_uri(uri)
    yield uri
    mlflow.set_tracking_uri(None)
