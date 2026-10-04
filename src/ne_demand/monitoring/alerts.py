"""Alert delivery and de-duplication.

Delivery: AWS SNS (email) when SNS_TOPIC_ARN is set, Slack when SLACK_WEBHOOK_URL
is set, and always the log. GitHub also emails the repo owner when a scheduled
workflow fails.

De-duplication (AlertState): a monitoring check that keeps failing alerts once when
it starts, reminds every 24 hours while it lasts, and sends one "resolved" message
when it clears, so an hourly monitor never floods the inbox.

    {root}/published/monitoring/alert_state.json
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import fsspec
import httpx

from ne_demand.config import Settings

log = logging.getLogger(__name__)

STATE = "published/monitoring/alert_state.json"
REMIND_AFTER = timedelta(hours=24)


def send_alert(text: str, subject: str = "ne-demand alert") -> None:
    log.error("ALERT: %s", text)
    settings = Settings()
    if settings.sns_topic_arn:
        try:
            import boto3

            boto3.client("sns", region_name=settings.sns_topic_arn.split(":")[3]).publish(
                TopicArn=settings.sns_topic_arn, Subject=subject[:100], Message=text
            )
        except Exception:
            log.exception("could not deliver SNS alert")
    if settings.slack_webhook_url:
        try:
            httpx.post(
                settings.slack_webhook_url.get_secret_value(),
                json={"text": f":rotating_light: *{subject}*\n{text}"},
                timeout=10,
            )
        except httpx.HTTPError:
            log.exception("could not deliver Slack alert")


class AlertState:
    """Firing/resolved state per check, persisted between monitoring runs."""

    def __init__(self, root: str, send: Callable[[str, str], None] = send_alert):
        self.root, self.send = root, send
        self.fs, self.path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/{STATE}")
        self.state: dict = {}
        if self.fs.exists(self.path):
            with self.fs.open(self.path, "r") as f:
                self.state = json.load(f)

    def update(self, checks: dict[str, str | None], now: datetime | None = None) -> list[str]:
        """checks: key -> problem message, or None when healthy. Returns what was sent."""
        now = now or datetime.now(UTC)
        sent = []
        for key, message in checks.items():
            prev = self.state.get(key, {"firing": False})
            if message:
                last = prev.get("last_sent")
                if not prev["firing"]:
                    self.send(message, f"[ne-demand] FIRING: {key}")
                    sent.append(f"firing {key}")
                    prev = {"firing": True, "since": now.isoformat(), "last_sent": now.isoformat()}
                elif last and now - datetime.fromisoformat(last) >= REMIND_AFTER:
                    self.send(
                        f"Still failing since {prev['since']}: {message}",
                        f"[ne-demand] STILL FIRING: {key}",
                    )
                    sent.append(f"reminder {key}")
                    prev["last_sent"] = now.isoformat()
                prev["message"] = message
            elif prev["firing"]:
                self.send(
                    f"{key} is healthy again (was failing since {prev['since']}).",
                    f"[ne-demand] RESOLVED: {key}",
                )
                sent.append(f"resolved {key}")
                prev = {"firing": False, "resolved_at": now.isoformat()}
            self.state[key] = prev
        self.fs.makedirs(self.path.rsplit("/", 1)[0], exist_ok=True)
        with self.fs.open(self.path, "w") as f:
            json.dump(self.state, f, indent=2)
        return sent
