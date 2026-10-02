from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ne_demand.ingestion import backfill as ingest
from ne_demand.ingestion import isone


def _fake_load(day: date) -> pd.DataFrame:
    return pd.DataFrame({"Time": [pd.Timestamp(day, tz="America/New_York")], "Load": [12000.0]})


def _files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.parquet"))


def test_backfill_writes_one_partition_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(isone, "fetch_load", _fake_load)
    n = ingest.backfill(str(tmp_path), "isone_load", date(2026, 3, 7), date(2026, 3, 9))
    assert n == 3
    dirs = {p.parent.name for p in _files(tmp_path)}
    assert dirs == {"date=2026-03-07", "date=2026-03-08", "date=2026-03-09"}


def test_rerunning_backfill_creates_no_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(isone, "fetch_load", _fake_load)
    ingest.backfill(str(tmp_path), "isone_load", date(2026, 3, 7), date(2026, 3, 9))
    before = _files(tmp_path)
    assert ingest.backfill(str(tmp_path), "isone_load", date(2026, 3, 7), date(2026, 3, 9)) == 0
    assert _files(tmp_path) == before


def test_failed_fetch_leaves_stored_data_intact(tmp_path, monkeypatch):
    monkeypatch.setattr(isone, "fetch_load", _fake_load)
    ingest.backfill(str(tmp_path), "isone_load", date(2026, 3, 7), date(2026, 3, 7))
    before = {p: p.read_bytes() for p in _files(tmp_path)}

    def boom(day):
        raise ConnectionError("ISO-NE down")

    monkeypatch.setattr(isone, "fetch_load", boom)
    assert ingest.backfill(str(tmp_path), "isone_load", date(2026, 3, 7), date(2026, 3, 8)) == 0
    assert {p: p.read_bytes() for p in _files(tmp_path)} == before


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        ingest.backfill(str(tmp_path), "nope", date(2026, 1, 1), date(2026, 1, 1))
