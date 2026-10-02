"""Read raw partitions back, tagging each row with when it was fetched."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import fsspec
import pandas as pd

_FETCHED = re.compile(r"fetched_at=(\d{8}T\d{6}Z)\.parquet$")


def raw_files(root: str, source: str, start: date, end: date) -> list[str]:
    fs, base = fsspec.core.url_to_fs(f"{root.rstrip('/')}/raw/{source}")
    files = []
    d = start
    while d <= end:
        part = f"{base}/date={d.isoformat()}"
        if fs.exists(part):
            files += [p for p in fs.ls(part, detail=False) if p.endswith(".parquet")]
        d += timedelta(days=1)
    return sorted(files)


def read_raw(root: str, source: str, start: date, end: date) -> pd.DataFrame:
    """All raw rows for `source` with partition dates in [start, end], plus `fetched_at`."""
    fs, _ = fsspec.core.url_to_fs(root)
    files = raw_files(root, source, start, end)
    if not files:
        return pd.DataFrame()

    def read(path: str) -> pd.DataFrame:
        with fs.open(path, "rb") as f:
            df = pd.read_parquet(f)
        df["fetched_at"] = pd.to_datetime(_FETCHED.search(path).group(1), utc=True)
        return df

    with ThreadPoolExecutor(max_workers=16) as pool:
        return pd.concat(pool.map(read, files), ignore_index=True)
