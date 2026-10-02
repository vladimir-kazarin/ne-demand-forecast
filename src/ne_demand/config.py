"""Runtime settings from the environment and training configs from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Temperature stations named in the PRD: one per major New England load center.
WEATHER_STATIONS: dict[str, tuple[float, float]] = {
    "boston": (42.3601, -71.0589),
    "hartford": (41.7658, -72.6734),
    "providence": (41.8240, -71.4128),
    "manchester": (42.9956, -71.4548),
}

LOCAL_TZ = "America/New_York"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    isone_username: str | None = None
    isone_password: SecretStr | None = None
    ne_data_root: str = "data"
    mlflow_tracking_uri: str | None = None
    slack_webhook_url: SecretStr | None = None


class TrainingWindow(BaseModel):
    lookback_days: int = 730
    holdout_days: int = 28


class TrainConfig(BaseModel):
    name: str
    seed: int = 42
    window: TrainingWindow = TrainingWindow()
    lag_hours: list[int] = [24, 168]
    lightgbm: dict[str, float | int | str] = {}


def load_train_config(path: str | Path) -> TrainConfig:
    with open(path) as f:
        return TrainConfig.model_validate(yaml.safe_load(f))
