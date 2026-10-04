"""A deployable model bundle: the booster plus the metadata needed to serve it.

    {model_dir}/model.txt       LightGBM booster
    {model_dir}/metadata.json   features, lags, issue time, registry version, lineage

The bundle is exported from the registry when the image is built, so each image
serves exactly one model version and starts without reaching MLflow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb

REQUIRED_METADATA = ["version", "registry_version", "git_commit", "features", "config"]


@dataclass(frozen=True)
class ModelBundle:
    booster: lgb.Booster
    metadata: dict

    @property
    def model_version(self) -> str:
        return f"ne-demand-lightgbm/v{self.metadata['registry_version']}"


def export_bundle(booster: lgb.Booster, metadata: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out / "model.txt"))
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
    return out


def load_bundle(model_dir: str | Path) -> ModelBundle:
    """Load and sanity-check a bundle. Raises on anything wrong, so a bad path or a
    corrupt model stops the service at startup instead of failing per request."""
    d = Path(model_dir)
    model_file, meta_file = d / "model.txt", d / "metadata.json"
    for f in (model_file, meta_file):
        if not f.is_file():
            raise FileNotFoundError(f"model bundle incomplete: {f} not found")
    metadata = json.loads(meta_file.read_text())
    missing = [k for k in REQUIRED_METADATA if k not in metadata]
    if missing:
        raise ValueError(f"model metadata missing keys: {missing}")
    try:
        booster = lgb.Booster(model_file=str(model_file))
    except lgb.basic.LightGBMError as e:
        raise ValueError(f"cannot load model from {model_file}: {e}") from None
    if booster.feature_name() != metadata["features"]:
        raise ValueError("model features do not match metadata features")
    return ModelBundle(booster, metadata)
