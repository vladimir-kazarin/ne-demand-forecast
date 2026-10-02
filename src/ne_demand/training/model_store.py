"""Model versions on the data root (replaced by the MLflow registry in Phase 2).

{root}/models/{version}/model.txt       LightGBM booster
{root}/models/{version}/metadata.json   config, data window, git commit, metrics
{root}/models/latest.json               {"version": ...}
"""

from __future__ import annotations

import json

import fsspec
import lightgbm as lgb


def _open(root: str, rel: str, mode: str):
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/models/{rel}")
    if "w" in mode:
        fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
    return fs.open(path, mode)


def save_model(root: str, booster: lgb.Booster, metadata: dict, make_latest: bool = True) -> None:
    version = metadata["version"]
    with _open(root, f"{version}/model.txt", "w") as f:
        f.write(booster.model_to_string())
    with _open(root, f"{version}/metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    if make_latest:
        with _open(root, "latest.json", "w") as f:
            json.dump({"version": version}, f)


def load_model(root: str, version: str | None = None) -> tuple[lgb.Booster, dict]:
    if version is None:
        try:
            with _open(root, "latest.json", "r") as f:
                version = json.load(f)["version"]
        except FileNotFoundError:
            raise FileNotFoundError(
                f"no model under {root}/models; run `ne-demand train`"
            ) from None
    with _open(root, f"{version}/model.txt", "r") as f:
        booster = lgb.Booster(model_str=f.read())
    with _open(root, f"{version}/metadata.json", "r") as f:
        metadata = json.load(f)
    return booster, metadata
