"""Post-deploy check: /health serves the expected model version and /predict answers.

uv run python scripts/check_api.py https://...lambda-url... --expect-version 3
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--expect-version", required=True)
    args = ap.parse_args()
    base = args.url.rstrip("/")
    want = f"ne-demand-lightgbm/v{args.expect_version}"

    # A fresh deploy cold-starts; allow it a few attempts.
    for attempt in range(6):
        try:
            health = httpx.get(f"{base}/health", timeout=30).json()
            if health.get("model_version") == want:
                break
            print(f"serving {health.get('model_version')}, want {want}; retrying")
        except (httpx.HTTPError, ValueError) as e:
            print(f"health check failed ({e}); retrying")
        time.sleep(5 * (attempt + 1))
    else:
        sys.exit(f"API is not serving {want}")

    day = datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    r = httpx.post(
        f"{base}/predict", json={"date": str(day), "hour": 12, "temperature_c": 15}, timeout=30
    )
    r.raise_for_status()
    print(f"OK: {want} at {health['git_commit'][:7]}, predict {r.json()['forecast_mw']:,.0f} MW")


if __name__ == "__main__":
    main()
