"""Run EvalScope with the custom AgentScope AliyunCS CLI runner."""

from __future__ import annotations

import os
import sys
from typing import Any

try:
    from evalscope import run_task
except ImportError:
    from evalscope.evalscope import run_task

from aliyuncs import ALIYUNCS_BASE_URL, get_api_key, get_model_name
from agentscope_aliyuncs_cli.cli import load_dotenv_file
from agentscope_aliyuncs_cli.constants import FRAMEWORK_NAME
import agentscope_aliyuncs_cli.runner  # noqa: F401  register custom runner


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def build_task_config() -> dict[str, Any]:
    """Build a small EvalScope task that evaluates the custom CLI."""

    load_dotenv_file()
    dataset = os.getenv("EVALSCOPE_DATASET", "gsm8k")
    model_name = os.getenv("EVALSCOPE_MODEL", get_model_name())

    return {
        "model": model_name,
        "model_id": os.getenv("EVALSCOPE_MODEL_ID", "agentscope_aliyuncs_cli"),
        "api_url": os.getenv("EVALSCOPE_API_URL", ALIYUNCS_BASE_URL),
        "api_key": os.getenv("EVALSCOPE_API_KEY") or get_api_key(),
        "eval_type": os.getenv("EVALSCOPE_EVAL_TYPE", "openai_api"),
        "datasets": [dataset],
        "dataset_args": {
            dataset: {
                "few_shot_num": _env_int("EVALSCOPE_FEW_SHOT_NUM", 0),
            },
        },
        "limit": _env_int("EVALSCOPE_LIMIT", 100),
        "eval_batch_size": _env_int("EVALSCOPE_BATCH_SIZE", 1),
        "generation_config": {
            "temperature": _env_float("EVALSCOPE_TEMPERATURE", 0.0),
            "max_tokens": _env_int("EVALSCOPE_MAX_TOKENS", 1024),
            "stream": False,
        },
        "agent_config": {
            "mode": "external",
            "framework": FRAMEWORK_NAME,
            "environment": "local",
            "timeout": _env_float("EVALSCOPE_AGENT_TIMEOUT", 300.0),
            "kwargs": {
                "python_bin": sys.executable,
                "project_dir": os.getcwd(),
                "protocol": os.getenv("AGENTSCOPE_CLI_PROTOCOL", "responses"),
            },
        },
        "judge_strategy": "rule",
        "collect_perf": True,
        "work_dir": os.getenv("EVALSCOPE_WORK_DIR", "outputs/agentscope_aliyuncs_cli"),
        "debug": os.getenv("EVALSCOPE_DEBUG", "false").lower() == "true",
    }


def main() -> None:
    run_task(build_task_config())


if __name__ == "__main__":
    main()
