from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "models.yaml"


def load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_provider_mode() -> str:
    return os.getenv("PROVIDER_MODE", "mock").lower()


def get_model_name(tier: str) -> str:
    env_key = f"{tier.upper()}_MODEL"
    if env_val := os.getenv(env_key):
        return env_val
    config = load_config()
    return config["models"][tier]["name"]
