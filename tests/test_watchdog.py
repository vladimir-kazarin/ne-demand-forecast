"""The AWS watchdog's decision logic (infra/aws/watchdog/handler.py)."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "watchdog", Path(__file__).resolve().parents[1] / "infra/aws/watchdog/handler.py"
)
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)

NOON_ET = datetime(2026, 10, 5, 16, 30, tzinfo=UTC)  # 12:30 EDT


def fresh(now):
    return {
        "load": now - timedelta(minutes=40),
        "monitor": now - timedelta(minutes=50),
        "forecast": now - timedelta(hours=2),
    }


def test_all_fresh_is_healthy():
    assert set(wd.evaluate(NOON_ET, fresh(NOON_ET)).values()) == {None}


def test_stale_demand_and_dead_monitor_are_flagged():
    m = fresh(NOON_ET) | {"load": NOON_ET - timedelta(hours=7), "monitor": None}
    checks = wd.evaluate(NOON_ET, m)
    assert "7.0 h ago" in checks["watchdog_data_freshness"]
    assert (
        checks["watchdog_monitor_heartbeat"] == "No record of the monitoring job in the data bucket"
    )


def test_forecast_due_only_after_noon_et():
    yesterday = fresh(NOON_ET) | {"forecast": NOON_ET - timedelta(days=1)}
    assert wd.evaluate(NOON_ET, yesterday)["watchdog_forecast_published"].startswith("No forecast")
    morning = NOON_ET - timedelta(hours=4)  # 08:30 ET: not due yet
    assert wd.evaluate(morning, yesterday)["watchdog_forecast_published"] is None


def test_dedupe_fires_once_reminds_daily_and_resolves():
    problem = {"watchdog_data_freshness": "stale"}
    state, sent = wd.dedupe({}, problem, NOON_ET)
    assert [s for s, _ in sent] == ["[ne-demand] FIRING: watchdog_data_freshness"]
    state, sent = wd.dedupe(state, problem, NOON_ET + timedelta(hours=1))
    assert sent == []
    state, sent = wd.dedupe(state, problem, NOON_ET + timedelta(hours=25))
    assert sent[0][0].startswith("[ne-demand] STILL FIRING")
    state, sent = wd.dedupe(state, {"watchdog_data_freshness": None}, NOON_ET + timedelta(hours=26))
    assert sent[0][0] == "[ne-demand] RESOLVED: watchdog_data_freshness"
