from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - depends on local environment
    yaml = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional local convenience
    def load_dotenv() -> None:
        return None

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "models.yaml"


def load_config() -> dict[str, Any]:
    if yaml is None:
        return _default_config()
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


def _default_config() -> dict[str, Any]:
    """Fallback matching config/models.yaml when PyYAML is unavailable."""

    return {
        "models": {
            "small": {
                "name": "gpt-4o-mini",
                "cost_per_1k_tokens": 0.15,
                "cost_multiplier": 1.0,
                "description": "低成本快速响应 (7B-14B 级别)",
            },
            "mid": {
                "name": "gpt-4o",
                "cost_per_1k_tokens": 2.50,
                "cost_multiplier": 5.0,
                "description": "成本与质量平衡 (13B-32B 级别)",
            },
            "large": {
                "name": "gpt-4",
                "cost_per_1k_tokens": 10.0,
                "cost_multiplier": 20.0,
                "description": "高质量推理 (70B+ / GPT-4 级别)",
            },
        },
        "router": {
            "length_thresholds": {
                "short": 100,
                "medium": 500,
            },
            "complexity_thresholds": {
                "low": 2,
                "medium": 5,
            },
            "reasoning_keywords": [
                "why",
                "prove",
                "compare",
                "explain",
                "analyze",
                "evaluate",
                "derive",
                "justify",
                "discuss",
                "contrast",
                "argue",
                "synthesize",
                "critique",
                "为什么",
                "证明",
                "比较",
                "分析",
                "解释",
                "推导",
                "论证",
            ],
            "weights": {
                "keyword": 0.4,
                "length": 0.3,
                "complexity": 0.3,
            },
        },
    }
