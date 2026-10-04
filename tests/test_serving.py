"""Prediction API: startup checks, parity with the batch forecast, and edge cases."""

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ne_demand.forecast.batch import run_forecast
from ne_demand.serving.app import create_app
from ne_demand.serving.bundle import export_bundle
from ne_demand.training.tracking import load_production
from ne_demand.training.train import train

pytestmark = pytest.mark.smoke

ISSUE = datetime(2026, 3, 19, 14, 30, tzinfo=UTC)  # 10:30 EDT
TARGET = date(2026, 3, 20)


@pytest.fixture
def served(tmp_path, tables, small_config):
    load, weather = tables
    (tmp_path / "processed").mkdir()
    load[load["time"] < pd.Timestamp(ISSUE).floor("h")].to_parquet(
        tmp_path / "processed" / "load_hourly.parquet", index=False
    )
    weather.to_parquet(tmp_path / "processed" / "weather_hourly.parquet", index=False)
    train(small_config, str(tmp_path), end_day=date(2026, 3, 18))
    model_dir = export_bundle(*load_production(), tmp_path / "model")
    app = create_app(str(model_dir), str(tmp_path), clock=lambda: pd.Timestamp(ISSUE))
    with TestClient(app) as client:
        yield client, tmp_path, model_dir


def test_health_reports_model_and_lineage(served):
    client, _, _ = served
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model_version"] == "ne-demand-lightgbm/v1"
    assert body["git_commit"]


def test_predict_matches_batch_forecast(served, tables):
    """Same inputs through the API and the batch job give the same number."""
    client, root, _ = served
    _, weather = tables
    flat = weather.assign(**{c: 7.5 for c in weather.columns if c.startswith("temp_")})
    batch = run_forecast(str(root), TARGET, ISSUE, temps=flat).set_index("time")

    r = client.post("/predict", json={"date": str(TARGET), "hour": 8, "temperature_c": 7.5})
    assert r.status_code == 200
    body = r.json()
    expected = batch.loc[pd.Timestamp(body["time_utc"]), "forecast_mw"]
    assert body["forecast_mw"] == pytest.approx(expected)
    assert body["lags_available"] == {
        "load_lag_24h": True,
        "load_lag_48h": True,
        "load_lag_168h": True,
    }


def test_afternoon_hour_masks_unknown_24h_lag(served):
    client, _, _ = served
    body = client.post(
        "/predict", json={"date": str(TARGET), "hour": 15, "temperature_c": 7.5}
    ).json()
    assert body["lags_available"]["load_lag_24h"] is False
    assert body["lags_available"]["load_lag_168h"] is True


def test_nonexistent_dst_hour_rejected(served):
    client, _, _ = served
    r = client.post("/predict", json={"date": "2026-03-08", "hour": 2, "temperature_c": 0})
    assert r.status_code == 422
    assert "DST" in r.json()["detail"]


@pytest.mark.parametrize("bad", [{"hour": 24}, {"temperature_c": 300}, {"date": "not-a-date"}])
def test_invalid_input_rejected(served, bad):
    client, _, _ = served
    req = {"date": str(TARGET), "hour": 8, "temperature_c": 5} | bad
    assert client.post("/predict", json=req).status_code == 422


def test_bad_model_path_fails_at_startup(tmp_path):
    app = create_app(str(tmp_path / "no-such-model"), None)
    with pytest.raises(FileNotFoundError, match="model bundle incomplete"), TestClient(app):
        pass


def test_corrupt_model_fails_at_startup(served, tmp_path):
    _, _, model_dir = served
    bad = Path(tmp_path / "corrupt")
    bad.mkdir()
    (bad / "metadata.json").write_text((model_dir / "metadata.json").read_text())
    (bad / "model.txt").write_text("not a model")
    with (
        pytest.raises(ValueError, match="cannot load model"),
        TestClient(create_app(str(bad), None)),
    ):
        pass


def test_missing_history_still_predicts_without_lags(served):
    _, _, model_dir = served
    with TestClient(create_app(str(model_dir), None)) as client:
        body = client.post(
            "/predict", json={"date": str(TARGET), "hour": 8, "temperature_c": 5}
        ).json()
    assert not any(body["lags_available"].values())
    assert body["forecast_mw"] > 0


def test_history_loads_on_a_freshly_booted_host(served, monkeypatch):
    """Lambda micro-VMs have a small monotonic clock; the first request must still load."""
    import ne_demand.serving.app as serving_app

    _, root, model_dir = served
    monkeypatch.setattr(serving_app.time, "monotonic", lambda: 3.0)  # 3 s since boot
    app = create_app(str(model_dir), str(root), clock=lambda: pd.Timestamp(ISSUE))
    with TestClient(app) as client:
        body = client.post(
            "/predict", json={"date": str(TARGET), "hour": 8, "temperature_c": 5}
        ).json()
    assert body["lags_available"]["load_lag_168h"] is True
