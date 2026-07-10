"""Run EvalScope through the OpenClaw CLI harness runner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from evalscope import run_task
except ImportError:
    from evalscope.evalscope import run_task

from openclaw_evalscope_cli.constants import FRAMEWORK_NAME
import openclaw_evalscope_cli.runner  # noqa: F401  register custom runner


def load_dotenv_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part for part in raw.split(os.pathsep) if part]


def _default_compose_files() -> list[str]:
    raw = _env_list("OPENCLAW_COMPOSE_FILES")
    if raw:
        return raw
    return [str(Path(__file__).resolve().with_name("docker-compose.evalscope.yml"))]


def build_task_config() -> dict[str, Any]:
    load_dotenv_file()

    dataset = os.getenv("EVALSCOPE_DATASET", "gsm8k")
    model_name = os.getenv("EVALSCOPE_MODEL", "mock")
    eval_type = os.getenv("EVALSCOPE_EVAL_TYPE", "mock_llm")

    cfg: dict[str, Any] = {
        "model": model_name,
        "model_id": os.getenv("EVALSCOPE_MODEL_ID", "openclaw_cli_harness"),
        "eval_type": eval_type,
        "datasets": [dataset],
        "dataset_args": {
            dataset: {
                "few_shot_num": _env_int("EVALSCOPE_FEW_SHOT_NUM", 0),
            },
        },
        "limit": _env_int("EVALSCOPE_LIMIT", 1),
        "eval_batch_size": 1,
        "generation_config": {
            "temperature": _env_float("EVALSCOPE_TEMPERATURE", 0.0),
            "max_tokens": _env_int("EVALSCOPE_MAX_TOKENS", 1024),
            "stream": False,
        },
        "agent_config": {
            "mode": "external",
            "framework": FRAMEWORK_NAME,
            "environment": "local",
            "bridge": {
                "proxy_host": os.getenv("EVALSCOPE_BRIDGE_PROXY_HOST", "0.0.0.0"),
            },
            "timeout": _env_float("EVALSCOPE_AGENT_TIMEOUT", 600.0),
            "kwargs": {
                "compose_project": os.getenv("OPENCLAW_COMPOSE_PROJECT", "openclaw-eval-baseline"),
                "compose_files": _default_compose_files(),
                "compose_dir": os.getenv("OPENCLAW_COMPOSE_DIR") or None,
                "gateway_service": os.getenv("OPENCLAW_GATEWAY_SERVICE", "openclaw-gateway"),
                "cli_service": os.getenv("OPENCLAW_CLI_SERVICE", "openclaw-cli"),
                "agent_id": os.getenv("OPENCLAW_AGENT_ID", "main"),
                "protocol": os.getenv("OPENCLAW_EVAL_PROTOCOL", "responses"),
                "bridge_host_for_container": os.getenv("OPENCLAW_BRIDGE_HOST_FOR_CONTAINER", "host.docker.internal"),
                "auto_up": _env_bool("OPENCLAW_AUTO_UP", True),
                "clean_workspace": _env_bool("OPENCLAW_CLEAN_WORKSPACE", True),
                "workspace_path": os.getenv("OPENCLAW_WORKSPACE_PATH", "/home/node/.openclaw/workspace"),
                "preserve_workspace_git": _env_bool("OPENCLAW_PRESERVE_WORKSPACE_GIT", True),
                "workspace_preserve_extra_entries": _env_list("OPENCLAW_WORKSPACE_PRESERVE_EXTRA_ENTRIES"),
                "workspace_clean_timeout_s": _env_float("OPENCLAW_WORKSPACE_CLEAN_TIMEOUT", 60.0),
            },
        },
        "judge_strategy": os.getenv("EVALSCOPE_JUDGE_STRATEGY", "rule"),
        "collect_perf": True,
        "work_dir": os.getenv("EVALSCOPE_WORK_DIR", "outputs/openclaw_cli_harness"),
        "debug": _env_bool("EVALSCOPE_DEBUG", False),
    }

    api_url = os.getenv("EVALSCOPE_API_URL")
    api_key = os.getenv("EVALSCOPE_API_KEY")
    dataset_dir = os.getenv("EVALSCOPE_DATASET_DIR")
    dataset_hub = os.getenv("EVALSCOPE_DATASET_HUB")
    if api_url:
        cfg["api_url"] = api_url
    if api_key:
        cfg["api_key"] = api_key
    if dataset_dir:
        cfg["dataset_dir"] = dataset_dir
    if dataset_hub:
        cfg["dataset_hub"] = dataset_hub

    return cfg


def main() -> None:
    run_task(build_task_config())


if __name__ == "__main__":
    main()
