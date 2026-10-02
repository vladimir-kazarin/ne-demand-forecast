"""Raw-zone layout: responses are stored unchanged as date-partitioned Parquet.

    {root}/raw/{source}/date=YYYY-MM-DD/fetched_at=YYYYMMDDTHHMMSSZ.parquet

Raw files are append-only and never rewritten; processed tables live under
{root}/processed/ and are rebuilt from raw.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def raw_partition_path(root: str, source: str, day: date, fetched_at: datetime) -> str:
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    stamp = fetched_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{root.rstrip('/')}/raw/{source}/date={day.isoformat()}/fetched_at={stamp}.parquet"
