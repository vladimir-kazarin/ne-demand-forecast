"""Freshness watchdog, run hourly by EventBridge Scheduler inside AWS.

GitHub's scheduler has skipped most runs on some days, and a job that never
starts cannot report its own failure. This function lives outside GitHub and
checks object timestamps in the data bucket:

- demand data (processed/load_hourly.parquet) updated in the last 3 hours
- the monitor's heartbeat (published/monitoring/status.json) in the last 3 hours
- tomorrow's forecast written today, once it is past 12:00 ET

Alerts go to SNS, de-duplicated like the monitor's: once when a check starts
failing, a reminder every 24 hours, and a resolved message. Standard library and
boto3 only, so it deploys as a plain zip.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MAX_AGE = timedelta(hours=3)
FORECAST_DUE = time(12, 0)
REMIND_AFTER = timedelta(hours=24)
STATE_KEY = "published/monitoring/watchdog_state.json"
OBJECTS = {
    "load": "processed/load_hourly.parquet",
    "monitor": "published/monitoring/status.json",
    "forecast": "published/forecasts.parquet",
}


def evaluate(now: datetime, modified: dict[str, datetime | None]) -> dict[str, str | None]:
    """Pure decision logic: check name -> problem, or None when healthy."""

    def stale(name: str, what: str) -> str | None:
        ts = modified.get(name)
        if ts is None:
            return f"No record of {what.lower()} in the data bucket"
        age = now - ts
        return (
            f"{what} last updated {age.total_seconds() / 3600:.1f} h ago (limit 3 h)"
            if age > MAX_AGE
            else None
        )

    local = now.astimezone(ET)
    forecast = modified.get("forecast")
    forecast_ok = local.time() < FORECAST_DUE or (
        forecast is not None and forecast.astimezone(ET).date() >= local.date()
    )
    return {
        "watchdog_data_freshness": stale("load", "Demand data"),
        "watchdog_monitor_heartbeat": stale("monitor", "The monitoring job"),
        "watchdog_forecast_published": None
        if forecast_ok
        else (f"No forecast written today ({local.date()}) by {FORECAST_DUE:%H:%M} ET"),
    }


def dedupe(
    state: dict, checks: dict[str, str | None], now: datetime
) -> tuple[dict, list[tuple[str, str]]]:
    """Returns (new state, messages to send as (subject, body))."""
    out = []
    for key, problem in checks.items():
        prev = state.get(key, {"firing": False})
        if problem:
            if not prev["firing"]:
                out.append((f"[ne-demand] FIRING: {key}", problem))
                prev = {"firing": True, "since": now.isoformat(), "last_sent": now.isoformat()}
            elif now - datetime.fromisoformat(prev["last_sent"]) >= REMIND_AFTER:
                out.append(
                    (f"[ne-demand] STILL FIRING: {key}", f"Since {prev['since']}: {problem}")
                )
                prev["last_sent"] = now.isoformat()
        elif prev["firing"]:
            out.append(
                (f"[ne-demand] RESOLVED: {key}", f"{key} is healthy again (since {prev['since']}).")
            )
            prev = {"firing": False}
        state[key] = prev
    return state, out


def handler(event, context):  # pragma: no cover - thin AWS wiring around evaluate/dedupe
    import boto3
    from botocore.exceptions import ClientError

    s3, sns = boto3.client("s3"), boto3.client("sns")
    bucket, topic = os.environ["BUCKET"], os.environ["TOPIC_ARN"]
    now = datetime.now(UTC)

    modified = {}
    for name, key in OBJECTS.items():
        try:
            modified[name] = s3.head_object(Bucket=bucket, Key=key)["LastModified"]
        except ClientError:
            modified[name] = None
    try:
        state = json.loads(s3.get_object(Bucket=bucket, Key=STATE_KEY)["Body"].read())
    except ClientError:
        state = {}

    checks = evaluate(now, modified)
    state, messages = dedupe(state, checks, now)
    for subject, body in messages:
        sns.publish(TopicArn=topic, Subject=subject[:100], Message=body)
    s3.put_object(Bucket=bucket, Key=STATE_KEY, Body=json.dumps(state).encode())
    return {"checks": checks, "sent": [s for s, _ in messages]}
