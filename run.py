"""Run the OpenClaw CLI harness against BrowseComp with task token metrics."""

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


def _safe_name(value: str) -> str:
    """Convert a model name into a report/path-safe identifier."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "model"


def configure_environment() -> None:
    """Configure a small real-model BrowseComp harness evaluation."""
    load_dotenv_file(PROJECT_ROOT / ".env")

    model_name = os.getenv("EVALSCOPE_MODEL") or get_model_name()
    api_key = os.getenv("EVALSCOPE_API_KEY") or os.getenv("ALIYUNCS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set ALIYUNCS_API_KEY or EVALSCOPE_API_KEY in the environment or project .env before running run.py"
        )

    state_dir = PROJECT_ROOT / "openclaw_evalscope_cli/.openclaw-eval/state"
    secret_dir = PROJECT_ROOT / "openclaw_evalscope_cli/.openclaw-eval/secrets"
    state_dir.mkdir(parents=True, exist_ok=True)
    secret_dir.mkdir(parents=True, exist_ok=True)

    # OpenClaw baseline runtime. Override any value from the shell for a
    # modified-image comparison without editing this file.
    _set_default("OPENCLAW_IMAGE", "openclaw-baseline:2026.6.11-srcsnap")
    _set_default("OPENCLAW_COMPOSE_PROJECT", "openclaw-eval-baseline")
    _set_default("OPENCLAW_GATEWAY_PORT", "18789")
    _set_default("OPENCLAW_EVAL_STATE_DIR", state_dir)
    _set_default("OPENCLAW_EVAL_SECRET_DIR", secret_dir)
    _set_default("OPENCLAW_CLEAN_WORKSPACE", "true")
    _set_default("OPENCLAW_PRESERVE_WORKSPACE_GIT", "true")

    # Evaluated model and benchmark.
    _set_default("EVALSCOPE_DATASET", "mmlu")
    _set_default("EVALSCOPE_LIMIT", "1")
    _set_default("EVALSCOPE_MODEL", model_name)
    _set_default("EVALSCOPE_MODEL_ID", f"openclaw_browsecomp_{_safe_name(model_name)}")
    _set_default("EVALSCOPE_EVAL_TYPE", "openai_api")
    _set_default("EVALSCOPE_API_URL", ALIYUNCS_BASE_URL)
    _set_default("EVALSCOPE_API_KEY", api_key)
    _set_default("EVALSCOPE_FEW_SHOT_NUM", "0")
    _set_default("EVALSCOPE_TEMPERATURE", "0.0")
    _set_default("EVALSCOPE_MAX_TOKENS", "2048")
    _set_default("EVALSCOPE_AGENT_TIMEOUT", "900")
    _set_default("EVALSCOPE_WORK_DIR", PROJECT_ROOT / "outputs/openclaw_browsecomp_token_metrics")

    # BrowseComp enables LLM-as-a-Judge in auto mode. The OpenClaw EvalScope
    # entrypoint reuses the evaluated model unless EVALSCOPE_JUDGE_* overrides
    # are provided. Judge calls are excluded from harness token totals.
    _set_default("EVALSCOPE_JUDGE_STRATEGY", "auto")
    _set_default("EVALSCOPE_JUDGE_MODEL", model_name)
    _set_default("EVALSCOPE_JUDGE_TEMPERATURE", "0.0")
    _set_default("EVALSCOPE_JUDGE_MAX_TOKENS", "4096")
    _set_default("EVALSCOPE_ANALYSIS_REPORT", "false")

    # Enables per-task prediction usage plus dataset-level Total/Avg/Min/Max
    # token columns in JSON, console output, and report.html.
    _set_default("EVALSCOPE_COLLECT_PERF", "true")


def main() -> None:
    configure_environment()
    run_evalscope()


if __name__ == "__main__":
    main()
