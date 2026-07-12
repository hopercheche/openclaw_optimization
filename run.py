"""Run the OpenClaw CLI harness with environment-overridable defaults.

Every default below uses ``os.environ.setdefault``. Shell variables or values
loaded from ``EVALSCOPE_ENV_FILE`` therefore take precedence. For parameters
not listed individually, ``EVALSCOPE_TASK_CONFIG`` can override any nested
EvalScope TaskConfig field as a JSON object.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from aliyuncs import ALIYUNCS_BASE_URL, get_model_name
from openclaw_evalscope_cli.run_evalscope import load_dotenv_file, main as run_evalscope


PROJECT_ROOT = Path(__file__).resolve().parent


def _set_default(name: str, value: str | Path) -> None:
    """Set a test default while preserving explicit shell configuration."""
    os.environ.setdefault(name, str(value))


def _set_defaults(values: dict[str, str | Path]) -> None:
    for name, value in values.items():
        _set_default(name, value)


def _safe_name(value: str) -> str:
    """Convert a model name into a report/path-safe identifier."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "model"


def configure_environment() -> None:
    """Configure a small real-model harness evaluation."""
    env_file = Path(os.getenv("EVALSCOPE_ENV_FILE", PROJECT_ROOT / ".env")).expanduser()
    load_dotenv_file(env_file)

    model_name = os.getenv("EVALSCOPE_MODEL") or get_model_name()
    api_key = os.getenv("EVALSCOPE_API_KEY") or os.getenv("ALIYUNCS_API_KEY")
    eval_type = os.getenv("EVALSCOPE_EVAL_TYPE", "openai_api")
    if not api_key and eval_type != "mock_llm" and not os.getenv("EVALSCOPE_TASK_CONFIG"):
        raise RuntimeError(
            "Set ALIYUNCS_API_KEY or EVALSCOPE_API_KEY in the environment or project .env before running run.py"
        )

    default_state_dir = PROJECT_ROOT / "openclaw_evalscope_cli/.openclaw-eval/state"
    default_secret_dir = PROJECT_ROOT / "openclaw_evalscope_cli/.openclaw-eval/secrets"
    dataset_name = os.getenv("EVALSCOPE_DATASET", "gsm8k")

    _set_defaults({
        # Docker/OpenClaw runtime.
        "OPENCLAW_IMAGE": "openclaw-baseline:2026.6.11-srcsnap",
        "OPENCLAW_COMPOSE_PROJECT": "openclaw-eval-baseline",
        "OPENCLAW_GATEWAY_SERVICE": "openclaw-gateway",
        "OPENCLAW_CLI_SERVICE": "openclaw-cli",
        "OPENCLAW_GATEWAY_PORT": "18789",
        "OPENCLAW_GATEWAY_TOKEN": "evalscope-local-token",
        "OPENCLAW_TZ": "UTC",
        "OPENCLAW_EVAL_STATE_DIR": default_state_dir,
        "OPENCLAW_EVAL_SECRET_DIR": default_secret_dir,
        "OPENCLAW_AGENT_ID": "main",
        "OPENCLAW_EVAL_PROTOCOL": "responses",
        "OPENCLAW_BRIDGE_HOST_FOR_CONTAINER": "host.docker.internal",
        "OPENCLAW_AUTO_UP": "true",
        "OPENCLAW_CLEAN_WORKSPACE": "true",
        "OPENCLAW_WORKSPACE_PATH": "/home/node/.openclaw/workspace",
        "OPENCLAW_PRESERVE_WORKSPACE_GIT": "true",
        "OPENCLAW_WORKSPACE_PRESERVE_EXTRA_ENTRIES": "",
        "OPENCLAW_WORKSPACE_CLEAN_TIMEOUT": "60",

        # EvalScope model, dataset, generation, and runtime.
        "EVALSCOPE_DATASET": dataset_name,
        "EVALSCOPE_LIMIT": "1",
        "EVALSCOPE_MODEL": model_name,
        "EVALSCOPE_MODEL_ID": f"openclaw_{_safe_name(model_name)}",
        "EVALSCOPE_EVAL_TYPE": eval_type,
        "EVALSCOPE_API_URL": ALIYUNCS_BASE_URL,
        "EVALSCOPE_FEW_SHOT_NUM": "0",
        "EVALSCOPE_BATCH_SIZE": "1",
        "EVALSCOPE_TEMPERATURE": "0.0",
        "EVALSCOPE_MAX_TOKENS": "2048",
        "EVALSCOPE_STREAM": "false",
        "EVALSCOPE_AGENT_ENVIRONMENT": "local",
        "EVALSCOPE_AGENT_TIMEOUT": "900",
        "EVALSCOPE_BRIDGE_PROXY_HOST": "0.0.0.0",
        "EVALSCOPE_OUTPUT_ROOT": PROJECT_ROOT / "outputs",
        "EVALSCOPE_DATASET_HUB": "modelscope",
        "EVALSCOPE_SEED": "42",
        "EVALSCOPE_DEBUG": "false",
        "EVALSCOPE_IGNORE_ERRORS": "false",
        "EVALSCOPE_RERUN_REVIEW": "false",
        "EVALSCOPE_NO_TIMESTAMP": "false",
        "EVALSCOPE_ENABLE_PROGRESS_TRACKER": "false",

        # Judge configuration. Separate EVALSCOPE_JUDGE_* variables override
        # the evaluated model; EVALSCOPE_JUDGE_MODEL_ARGS overrides them all.
        "EVALSCOPE_JUDGE_STRATEGY": "auto",
        "EVALSCOPE_JUDGE_MODEL": model_name,
        "EVALSCOPE_JUDGE_EVAL_TYPE": eval_type,
        "EVALSCOPE_JUDGE_TEMPERATURE": "0.0",
        "EVALSCOPE_JUDGE_MAX_TOKENS": "4096",
        "EVALSCOPE_ANALYSIS_REPORT": "false",
        "EVALSCOPE_COLLECT_PERF": "true",
    })

    if api_key:
        _set_default("EVALSCOPE_API_KEY", api_key)

    # Create the effective, possibly overridden bind-mount directories.
    Path(os.environ["OPENCLAW_EVAL_STATE_DIR"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(os.environ["OPENCLAW_EVAL_SECRET_DIR"]).expanduser().mkdir(parents=True, exist_ok=True)


def main() -> None:
    configure_environment()
    run_evalscope()


if __name__ == "__main__":
    main()
