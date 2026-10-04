"""Shared data access, palette and chart helpers for the app's pages.

Reads only what the pipeline publishes; no pipeline code is imported, so the app
installs in seconds on Streamlit Community Cloud.
"""

from __future__ import annotations

import json
import os

import fsspec
import pandas as pd
import streamlit as st

LOCAL_TZ = "America/New_York"
REPO_URL = "https://github.com/vladimir-kazarin/ne-demand-forecast"

# Reference palette, categorical slots 1-3, validated light and dark (dataviz validator).
# Actual demand is the reference line, drawn in primary ink rather than a series hue.
PALETTE = {
    "light": {
        "actual": "#0b0b0b",
        "model": "#2a78d6",
        "iso": "#eb6834",
        "naive": "#1baf7a",
        "grid": "#e6e5e0",
        "muted": "#52514e",
        "label_bg": "rgba(255,255,255,0.85)",
    },
    "dark": {
        "actual": "#ffffff",
        "model": "#3987e5",
        "iso": "#d95926",
        "naive": "#199e70",
        "grid": "#383835",
        "muted": "#c3c2b7",
        "label_bg": "rgba(14,17,23,0.85)",
    },
}


def colors() -> dict:
    theme = getattr(getattr(st, "context", None), "theme", None)
    return PALETTE["dark" if getattr(theme, "type", None) == "dark" else "light"]


def secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:  # no secrets file outside Streamlit Cloud
        return default


def _root() -> str:
    return secret("NE_DATA_ROOT") or os.environ.get("NE_DATA_ROOT", "data")


def _storage_options() -> dict:
    aws = secret("aws")
    return {"key": aws["access_key_id"], "secret": aws["secret_access_key"]} if aws else {}


@st.cache_data(ttl=600, show_spinner=False)
def read_bytes(rel: str) -> bytes | None:
    try:
        with fsspec.open(f"{_root().rstrip('/')}/{rel}", "rb", **_storage_options()) as f:
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return None


@st.cache_data(ttl=600, show_spinner=False)
def read_table(rel: str) -> pd.DataFrame:
    try:
        with fsspec.open(f"{_root().rstrip('/')}/{rel}", "rb", **_storage_options()) as f:
            return pd.read_parquet(f)
    # The app's key may read but not list the bucket, so S3 reports a file that does not
    # exist yet as 403 Forbidden rather than 404. Both mean "nothing published yet".
    except (FileNotFoundError, PermissionError):
        return pd.DataFrame()


def read_json(rel: str) -> dict:
    raw = read_bytes(rel)
    return json.loads(raw) if raw else {}


def local_wall_time(ts: pd.Series | pd.DatetimeIndex):
    """UTC -> New England wall-clock time without tz, so charts show local hours."""
    return pd.DatetimeIndex(ts).tz_convert(LOCAL_TZ).tz_localize(None)
