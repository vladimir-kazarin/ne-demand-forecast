"""One monitoring cycle end to end on synthetic data, with a captured alert sender."""

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from conftest import synthetic_tables

from ne_demand.monitoring.monitor import run_monitor

NOW = datetime(2026, 3, 20, 13, 0, tzinfo=UTC)  # 09:00 ET, before the forecast is due


class Outbox:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def __call__(self, text: str, subject: str) -> None:
        self.messages.append((subject, text))

    def subjects(self) -> list[str]:
        return [s for s, _ in self.messages]


@pytest.fixture
def root(tmp_path):
    load, weather = synthetic_tables(days=420)
    (tmp_path / "processed").mkdir()
    load[load["time"] < pd.Timestamp(NOW)].to_parquet(
        tmp_path / "processed" / "load_hourly.parquet", index=False
    )
    weather.to_parquet(tmp_path / "processed" / "weather_hourly.parquet", index=False)
    return tmp_path


def test_healthy_cycle_sends_nothing_and_writes_status(root):
    out = Outbox()
    status = run_monitor(str(root), NOW, send=out)
    assert out.messages == []
    assert set(status["checks"].values()) == {"ok"}
    saved = json.loads((root / "published/monitoring/status.json").read_text())
    assert saved["checks"]["input_drift"] == "ok"
    assert (root / "published/monitoring/drift_history.parquet").exists()
    assert (root / "published/monitoring/drift_latest.parquet").exists()


def test_injected_shift_fires_an_alert_in_one_cycle(root):
    """PRD Phase 6 acceptance: an injected input shift fires an alert within one cycle."""
    out = Outbox()
    status = run_monitor(str(root), NOW, inject={"temp_boston": 8.0}, send=out)
    assert len(out.messages) == 1
    subject, text = out.messages[0]
    assert "DRILL" in subject and "boston" in text and "data fault" in text
    assert "drill" in status["drift_note"]
    # a drill never leaves a real alert firing
    assert status["checks"]["input_drift"] == "ok"


def test_stale_data_alerts_once_then_resolves(root):
    out = Outbox()
    later = NOW + timedelta(days=5)  # no new data for days: ingestion stopped
    run_monitor(str(root), later, send=out)
    assert "[ne-demand] FIRING: data_freshness" in out.subjects()

    out.messages.clear()
    run_monitor(str(root), later + timedelta(hours=1), send=out)
    assert not any("data_freshness" in s for s in out.subjects())  # no hourly repeat

    run_monitor(str(root), later + timedelta(hours=25), send=out)
    assert "[ne-demand] STILL FIRING: data_freshness" in out.subjects()  # daily reminder

    out.messages.clear()
    run_monitor(str(root), NOW, send=out)  # data is fresh again
    assert "[ne-demand] RESOLVED: data_freshness" in out.subjects()


def test_missing_forecast_after_noon_alerts(root):
    out = Outbox()
    afternoon = NOW + timedelta(hours=5)  # 14:00 ET, nothing published for tomorrow
    status = run_monitor(str(root), afternoon, send=out)
    assert status["checks"]["forecast_published"].startswith("no forecast for 2026-03-21")
    assert "[ne-demand] FIRING: forecast_published" in out.subjects()


def test_drift_runs_once_per_day(root):
    run_monitor(str(root), NOW, send=Outbox())
    run_monitor(str(root), NOW + timedelta(hours=1), send=Outbox())
    history = pd.read_parquet(root / "published/monitoring/drift_history.parquet")
    assert len(history) == 1
