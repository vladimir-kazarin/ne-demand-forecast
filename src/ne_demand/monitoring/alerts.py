"""Failure alerts. Posts to Slack when SLACK_WEBHOOK_URL is set; always logs.

GitHub also emails the repo owner when a scheduled workflow fails, so a
failure is never silent even before Slack is configured.
"""

from __future__ import annotations

import logging

import httpx

from ne_demand.config import Settings

log = logging.getLogger(__name__)


def send_alert(text: str) -> None:
    log.error("ALERT: %s", text)
    url = Settings().slack_webhook_url
    if url is None:
        return
    try:
        httpx.post(url.get_secret_value(), json={"text": f":rotating_light: {text}"}, timeout=10)
    except httpx.HTTPError:
        log.exception("could not deliver Slack alert")
