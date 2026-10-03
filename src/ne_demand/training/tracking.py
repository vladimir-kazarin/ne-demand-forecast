"""MLflow tracking and model registry.

Every training run logs its config, metrics, data window, data hash, and git
commit. The model is registered as a new version of REGISTERED_MODEL and gets
the `candidate` alias; `production` moves only through `promote` (the Phase 4
gate will call it). Lineage lives on the model version itself, so the registry
alone answers "what is in production and what produced it".
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

import lightgbm as lgb
import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

log = logging.getLogger(__name__)

EXPERIMENT = "ne-demand-forecast"
REGISTERED_MODEL = "ne-demand-lightgbm"
CANDIDATE, PRODUCTION = "candidate", "production"


def data_hash(frame: pd.DataFrame) -> str:
    """Content hash of the exact training frame (features and target)."""
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).to_numpy()).hexdigest()[:16]


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        out |= _flatten(v, f"{key}.") if isinstance(v, dict) else {key: v}
    return out


def log_and_register(booster: lgb.Booster, metadata: dict) -> str:
    """Log the run, register the model, alias it `candidate`. Returns the registry version."""
    mlflow.set_experiment(EXPERIMENT)
    lineage = {
        "git_commit": metadata["git_commit"],
        "data_hash": metadata["data_hash"],
        **{f"data.{k}": str(v) for k, v in metadata["data_window"].items()},
    }
    with mlflow.start_run(run_name=metadata["version"]) as run:
        mlflow.log_params(_flatten(metadata["config"]))
        mlflow.log_metrics(metadata["metrics"])
        mlflow.set_tags(lineage | {"model_id": metadata["version"]})
        mlflow.log_dict(metadata, "metadata.json")
        info = mlflow.lightgbm.log_model(
            booster, name="model", registered_model_name=REGISTERED_MODEL
        )

    version = str(info.registered_model_version)
    client = MlflowClient()
    for k, v in (lineage | {"run_id": run.info.run_id, "model_id": metadata["version"]}).items():
        client.set_model_version_tag(REGISTERED_MODEL, version, k, v)
    client.set_registered_model_alias(REGISTERED_MODEL, CANDIDATE, version)
    log.info("registered %s v%s as %s", REGISTERED_MODEL, version, CANDIDATE)
    return version


def production_version() -> str | None:
    try:
        return str(MlflowClient().get_model_version_by_alias(REGISTERED_MODEL, PRODUCTION).version)
    except MlflowException:
        return None


def promote(version: str, reason: str) -> None:
    """Point `production` at `version` and record why on the version itself."""
    client = MlflowClient()
    previous = production_version()
    client.set_registered_model_alias(REGISTERED_MODEL, PRODUCTION, version)
    tags = {
        "promoted_at": datetime.now(UTC).isoformat(),
        "promotion_reason": reason,
        "previous_production": previous or "none",
    }
    for k, v in tags.items():
        client.set_model_version_tag(REGISTERED_MODEL, version, k, v)
    log.info("production: v%s -> v%s (%s)", previous, version, reason)


def load_production() -> tuple[lgb.Booster, dict]:
    """The production booster and its training metadata (features, lags, lineage)."""
    client = MlflowClient()
    try:
        mv = client.get_model_version_by_alias(REGISTERED_MODEL, PRODUCTION)
    except MlflowException:
        raise LookupError(
            f"no '{PRODUCTION}' alias on {REGISTERED_MODEL}; train and promote a model first"
        ) from None
    booster = mlflow.lightgbm.load_model(f"models:/{REGISTERED_MODEL}@{PRODUCTION}")
    metadata = mlflow.artifacts.load_dict(f"runs:/{mv.run_id}/metadata.json")
    metadata["registry_version"] = str(mv.version)
    return booster, metadata
