"""Prediction API.

    GET  /health   model version and lineage; 200 only once the model is loaded
    POST /predict  {date, hour, temperature_c} -> forecast MW for that local hour

Features come from the same `build_features` the batch forecast uses. Lagged
demand is read from the processed load table as known at that day's scheduled
issue time (or now, if earlier), so an API prediction matches what the batch
job would issue for the same inputs.

Run locally:  MODEL_DIR=build/model uv run --extra serving uvicorn ne_demand.serving.app:app
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ne_demand.config import LOCAL_TZ
from ne_demand.features.build import (
    TEMP_COLUMNS,
    build_features,
    scheduled_issue_time,
    target_hours,
)
from ne_demand.processing import read_processed
from ne_demand.serving.bundle import ModelBundle, load_bundle

log = logging.getLogger(__name__)

HISTORY_TTL_SECONDS = 600


class PredictRequest(BaseModel):
    date: dt.date = Field(description="Local (ET) calendar day")
    hour: int = Field(ge=0, le=23, description="Local (ET) hour start, 0-23")
    temperature_c: float = Field(ge=-45, le=50, description="Forecast temperature, °C")


class PredictResponse(BaseModel):
    date: dt.date
    hour: int
    time_utc: dt.datetime
    forecast_mw: float
    model_version: str
    model_id: str
    git_commit: str
    issue_time: dt.datetime
    lags_available: dict[str, bool]


class LoadHistory:
    """Processed hourly load, refreshed at most every HISTORY_TTL_SECONDS."""

    def __init__(self, root: str | None):
        self.root = root
        # Typed empty history (UTC hourly index), so "no data" flows through the feature code.
        self._series = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
        self._loaded_at = 0.0

    def get(self) -> pd.Series:
        if self.root and time.monotonic() - self._loaded_at > HISTORY_TTL_SECONDS:
            try:
                df = read_processed(self.root, "load_hourly")
                self._series = df.set_index("time")["load_mw"] if not df.empty else self._series
            except Exception:
                # Serve without lags rather than fail; the response says which are missing.
                log.exception("could not refresh load history from %s", self.root)
            self._loaded_at = time.monotonic()
        return self._series


def create_app(
    model_dir: str | None = None,
    data_root: str | None = None,
    clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
) -> FastAPI:
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        path = model_dir or os.environ.get("MODEL_DIR", "/opt/model")
        state["bundle"] = load_bundle(path)  # raises on a bad path: the service never starts
        state["history"] = LoadHistory(data_root or os.environ.get("NE_DATA_ROOT"))
        log.info("serving %s from %s", state["bundle"].model_version, path)
        yield

    app = FastAPI(title="New England demand forecast", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        b: ModelBundle = state["bundle"]
        return {
            "status": "ok",
            "model_version": b.model_version,
            "model_id": b.metadata["version"],
            "git_commit": b.metadata["git_commit"],
            "data_window": b.metadata.get("data_window"),
        }

    @app.post("/predict", response_model=PredictResponse)
    def predict(req: PredictRequest) -> PredictResponse:
        b: ModelBundle = state["bundle"]
        cfg = b.metadata["config"]
        hours = target_hours(req.date)
        local_hours = hours.tz_convert(LOCAL_TZ).hour
        matches = hours[local_hours == req.hour]
        if matches.empty:
            raise HTTPException(422, f"{req.hour}:00 does not exist on {req.date} (DST change)")
        target = pd.DatetimeIndex([matches[0]])

        issue_local = dt.time.fromisoformat(cfg["issue_time_local"])
        issue = min(scheduled_issue_time(req.date, issue_local), clock())
        temps = pd.DataFrame({c: [req.temperature_c] for c in TEMP_COLUMNS}, index=target)
        feats = build_features(state["history"].get(), temps, target, issue, cfg["lag_hours"])
        lag_cols = [c for c in feats.columns if c.startswith("load_lag_")]

        return PredictResponse(
            date=req.date,
            hour=req.hour,
            time_utc=target[0].to_pydatetime(),
            forecast_mw=float(b.booster.predict(feats[b.metadata["features"]])[0]),
            model_version=b.model_version,
            model_id=b.metadata["version"],
            git_commit=b.metadata["git_commit"],
            issue_time=issue.to_pydatetime(),
            lags_available={c: bool(feats[c].notna().iloc[0]) for c in lag_cols},
        )

    return app


app = create_app()
