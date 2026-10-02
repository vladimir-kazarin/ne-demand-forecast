from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ne_demand.config import load_train_config
from ne_demand.ingestion.storage import raw_partition_path

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_train_config_loads():
    cfg = load_train_config(ROOT / "configs" / "lightgbm_v1.yaml")
    assert cfg.lag_hours == [24, 168]


def test_raw_partition_path():
    path = raw_partition_path(
        "s3://bucket/ne/", "isone_load", date(2026, 3, 8), datetime(2026, 3, 8, 6, 5, tzinfo=UTC)
    )
    assert (
        path == "s3://bucket/ne/raw/isone_load/date=2026-03-08/fetched_at=20260308T060500Z.parquet"
    )


def test_raw_partition_path_requires_aware_timestamp():
    with pytest.raises(ValueError):
        raw_partition_path("data", "x", date(2026, 1, 1), datetime(2026, 1, 1))  # noqa: DTZ001
