"""Raw-zone layout: responses are stored unchanged as date-partitioned Parquet.

    {root}/raw/{source}/date=YYYY-MM-DD/fetched_at=YYYYMMDDTHHMMSSZ.parquet

Raw files are append-only and never rewritten; processed tables live under
{root}/processed/ and are rebuilt from raw. `root` is a local path or an
s3:// URL — fsspec handles both.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import fsspec
import pandas as pd


def raw_partition_path(root: str, source: str, day: date, fetched_at: datetime) -> str:
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    stamp = fetched_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{root.rstrip('/')}/raw/{source}/date={day.isoformat()}/fetched_at={stamp}.parquet"


def partition_exists(root: str, source: str, day: date) -> bool:
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/raw/{source}/date={day.isoformat()}")
    return fs.exists(path) and bool(fs.ls(path))


def write_raw(df: pd.DataFrame, root: str, source: str, day: date, fetched_at: datetime) -> str:
    path = raw_partition_path(root, source, day, fetched_at)
    fs, fs_path = fsspec.core.url_to_fs(path)
    fs.makedirs(fs_path.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(fs_path, "wb") as f:
        df.to_parquet(f, index=False)
    return path
