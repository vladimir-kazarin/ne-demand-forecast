"""Shared retry policy for external API calls."""

from __future__ import annotations

import logging

from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

retrying = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, max=30),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
