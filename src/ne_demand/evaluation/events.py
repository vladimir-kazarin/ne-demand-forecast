"""Model event log: every registration, gate decision, promotion and rollback.

    {root}/published/model_events.parquet

Append-only and published, so the dashboard's model timeline reads the same
record the pipeline writes. The registry holds the same facts as version tags.
"""

from __future__ import annotations

from datetime import UTC, datetime

import fsspec
import pandas as pd

EVENTS = "published/model_events.parquet"
COLUMNS = [
    "at",
    "event",
    "version",
    "from_version",
    "reason",
    "candidate_mape",
    "production_mape",
    "naive_mape",
    "holdout_start",
    "holdout_end",
]


def read_events(root: str) -> pd.DataFrame:
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/{EVENTS}")
    if not fs.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    with fs.open(path, "rb") as f:
        return pd.read_parquet(f)


def append_event(root: str, event: str, version: str, reason: str, **fields) -> dict:
    row = (
        {c: None for c in COLUMNS}
        | fields
        | {"at": datetime.now(UTC), "event": event, "version": str(version), "reason": reason}
    )
    events = pd.concat([read_events(root), pd.DataFrame([row])], ignore_index=True)
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/{EVENTS}")
    fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
    with fs.open(path, "wb") as f:
        events[COLUMNS].astype(
            {"from_version": "string", "holdout_start": "string", "holdout_end": "string"}
        ).to_parquet(f, index=False)
    return row
