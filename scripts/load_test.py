"""Latency check for the prediction API: p50/p95/p99 over N requests at concurrency C.

uv run python scripts/load_test.py http://localhost:8080 --requests 500 --concurrency 10
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--requests", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--p95-budget-ms", type=float, default=200)
    args = ap.parse_args()

    base = args.url.rstrip("/")
    tomorrow = datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    client = httpx.Client(timeout=30)
    client.get(f"{base}/health").raise_for_status()  # warm up, and fail early if down

    def one(_: int) -> tuple[float, int]:
        body = {
            "date": str(tomorrow - timedelta(days=random.randint(0, 30))),
            "hour": random.choice([0, 6, 9, 12, 15, 18, 21]),
            "temperature_c": round(random.uniform(-10, 32), 1),
        }
        t0 = time.perf_counter()
        r = client.post(f"{base}/predict", json=body)
        return (time.perf_counter() - t0) * 1000, r.status_code

    with ThreadPoolExecutor(args.concurrency) as pool:
        results = list(pool.map(one, range(args.requests)))
    ms = sorted(r[0] for r in results)
    errors = sum(1 for r in results if r[1] != 200)
    q = statistics.quantiles(ms, n=100)
    p95 = q[94]
    print(f"{args.requests} requests, concurrency {args.concurrency}, errors {errors}")
    print(f"p50 {q[49]:.1f} ms  p95 {p95:.1f} ms  p99 {q[98]:.1f} ms  max {ms[-1]:.1f} ms")
    ok = errors == 0 and p95 <= args.p95_budget_ms
    print("PASS" if ok else f"FAIL (budget p95 <= {args.p95_budget_ms} ms, 0 errors)")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
