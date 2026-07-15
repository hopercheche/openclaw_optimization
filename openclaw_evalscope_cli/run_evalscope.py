"""Run EvalScope through the OpenClaw CLI harness runner."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from evalscope import run_task
except ImportError:
    from evalscope.evalscope import run_task
from evalscope.config import parse_task_config

from openclaw_evalscope_cli.constants import FRAMEWORK_NAME
from openclaw_evalscope_cli.experiment_report import generate_experiment_report
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


def _env_number(name: str, default: int | float) -> int | float:
    raw = os.getenv(name, str(default))
    value = float(raw)
    return int(value) if value.is_integer() else value


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part for part in raw.split(os.pathsep) if part]


def _env_json_object(name: str) -> dict[str, Any] | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a valid JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must decode to a JSON object")
    if name == "EVALSCOPE_JUDGE_MODEL_ARGS" and "model" in value and "model_id" not in value:
        raise ValueError(f'{name} uses "model_id", not "model", for the judge model name')
    return value


def _env_datasets() -> list[str]:
    raw = os.getenv("EVALSCOPE_DATASETS")
    if not raw:
        return [os.getenv("EVALSCOPE_DATASET", "gsm8k")]
    raw = raw.strip()
    if raw.startswith("["):
        value = json.loads(raw)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("EVALSCOPE_DATASETS must be a JSON string list")
        return value
    return [item.strip() for item in raw.split(",") if item.strip()]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge JSON configuration objects."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _safe_path_component(value: Any) -> str:
    """Convert a config value into a stable output-directory component."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._-")
    return text or "unknown"


def _default_work_dir(cfg: dict[str, Any]) -> str:
    output_root = Path(os.getenv("EVALSCOPE_OUTPUT_ROOT", "outputs")).expanduser()
    model_id = _safe_path_component(cfg.get("model_id", "model"))
    datasets = cfg.get("datasets") or ["dataset"]
    dataset_id = "__".join(_safe_path_component(dataset) for dataset in datasets)
    return str(output_root / f"{model_id}__{dataset_id}")


def _default_compose_files() -> list[str]:
    raw = _env_list("OPENCLAW_COMPOSE_FILES")
    if raw:
        return raw
    files = [str(Path(__file__).resolve().with_name("docker-compose.evalscope.yml"))]
    if _env_bool("OPENCLAW_ROUTER_ENABLED", False):
        files.append(str(Path(__file__).resolve().with_name("docker-compose.router.yml")))
    return files


def _build_router_config(
    *,
    generation_config: dict[str, Any],
    default_eval_type: str,
    default_api_url: str | None,
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    routes = _env_json_object("EVALSCOPE_ROUTER_MODEL_ROUTES") or {}
    tiers = _env_json_object("OPENCLAW_ROUTER_TIERS") or {}
    if set(tiers) != {"small", "mid", "large"}:
        raise ValueError("OPENCLAW_ROUTER_TIERS must contain exactly small, mid, and large")
    unknown_targets = set(tiers.values()) - set(routes)
    if unknown_targets:
        raise ValueError(
            "OPENCLAW_ROUTER_TIERS references models missing from "
            f"EVALSCOPE_ROUTER_MODEL_ROUTES: {sorted(unknown_targets)}"
        )

    bridge_routes: dict[str, Any] = {}
    openclaw_models: list[dict[str, Any]] = []
    for request_model, raw_route in routes.items():
        if not isinstance(raw_route, dict):
            raise ValueError(f"router model route {request_model!r} must be an object")
        eval_type = str(raw_route.get("eval_type") or default_eval_type)
        bridge_route: dict[str, Any] = {
            "model_id": str(raw_route.get("model_id") or request_model),
            "eval_type": eval_type,
            "generation_config": _deep_merge(
                generation_config,
                raw_route.get("generation_config") or {},
            ),
            "model_args": raw_route.get("model_args") or {},
        }
        route_api_url = raw_route.get("api_url") or default_api_url
        if route_api_url:
            bridge_route["api_url"] = route_api_url
        api_key_env = raw_route.get("api_key_env")
        if api_key_env:
            bridge_route["api_key_env"] = str(api_key_env)
        elif eval_type not in {"mock_llm", "mock_llm_with_sleep"} and os.getenv("EVALSCOPE_API_KEY"):
            bridge_route["api_key_env"] = "EVALSCOPE_API_KEY"
        bridge_routes[str(request_model)] = bridge_route

        model_config = raw_route.get("openclaw_model") or {}
        if not isinstance(model_config, dict):
            raise ValueError(f"router route {request_model!r}.openclaw_model must be an object")
        openclaw_models.append({
            "id": str(request_model),
            "name": str(model_config.get("name") or request_model),
            "reasoning": bool(model_config.get("reasoning", True)),
            "input": model_config.get("input") or ["text"],
            "cost": model_config.get("cost") or {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
            },
            "contextWindow": int(model_config.get("contextWindow", 131072)),
            "maxTokens": int(model_config.get("maxTokens", generation_config.get("max_tokens") or 8192)),
        })
    return bridge_routes, {key: str(value) for key, value in tiers.items()}, openclaw_models


def build_task_config() -> dict[str, Any]:
    load_dotenv_file()

    datasets = _env_datasets()
    model_name = os.getenv("EVALSCOPE_MODEL", "mock")
    eval_type = os.getenv("EVALSCOPE_EVAL_TYPE", "mock_llm")
    api_url = os.getenv("EVALSCOPE_API_URL")
    api_key = os.getenv("EVALSCOPE_API_KEY")

    judge_model_args = _env_json_object("EVALSCOPE_JUDGE_MODEL_ARGS")
    if judge_model_args is None:
        judge_model_args = {
            "model_id": os.getenv("EVALSCOPE_JUDGE_MODEL", model_name),
            "eval_type": os.getenv("EVALSCOPE_JUDGE_EVAL_TYPE", eval_type),
            "generation_config": {
                "temperature": _env_float("EVALSCOPE_JUDGE_TEMPERATURE", 0.0),
                "max_tokens": _env_int("EVALSCOPE_JUDGE_MAX_TOKENS", 4096),
            },
        }
        judge_api_url = os.getenv("EVALSCOPE_JUDGE_API_URL") or api_url
        judge_api_key = os.getenv("EVALSCOPE_JUDGE_API_KEY") or api_key
        if judge_api_url:
            judge_model_args["api_url"] = judge_api_url
        if judge_api_key:
            judge_model_args["api_key"] = judge_api_key

    default_dataset_args = {
        dataset: {"few_shot_num": _env_int("EVALSCOPE_FEW_SHOT_NUM", 0)}
        for dataset in datasets
    }
    dataset_args = _deep_merge(
        default_dataset_args,
        _env_json_object("EVALSCOPE_DATASET_ARGS") or {},
    )
    generation_config = _deep_merge(
        {
            "temperature": _env_float("EVALSCOPE_TEMPERATURE", 0.0),
            "max_tokens": _env_int("EVALSCOPE_MAX_TOKENS", 1024),
            "stream": _env_bool("EVALSCOPE_STREAM", False),
        },
        _env_json_object("EVALSCOPE_GENERATION_CONFIG") or {},
    )
    router_enabled = _env_bool("OPENCLAW_ROUTER_ENABLED", False)
    context_index_enabled = _env_bool("OPENCLAW_CONTEXT_INDEX_ENABLED", False)
    context_index_config = _env_json_object("OPENCLAW_CONTEXT_INDEX_CONFIG") or {}
    planner_enabled = _env_bool("OPENCLAW_PLANNER_ENABLED", False)
    planner_config = _env_json_object("OPENCLAW_PLANNER_CONFIG") or {}
    bridge_routes: dict[str, Any] = {}
    router_tiers: dict[str, str] = {}
    router_models: list[dict[str, Any]] = []
    if router_enabled:
        bridge_routes, router_tiers, router_models = _build_router_config(
            generation_config=generation_config,
            default_eval_type=eval_type,
            default_api_url=api_url,
        )
        state_root = Path.cwd() / "openclaw_evalscope_cli" / ".openclaw-eval"
        os.environ.setdefault("OPENCLAW_EVAL_STATE_DIR", str(state_root / "router-state"))
        os.environ.setdefault("OPENCLAW_EVAL_SECRET_DIR", str(state_root / "router-secrets"))
        Path(os.environ["OPENCLAW_EVAL_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
        Path(os.environ["OPENCLAW_EVAL_SECRET_DIR"]).mkdir(parents=True, exist_ok=True)
    elif context_index_enabled:
        state_root = Path.cwd() / "openclaw_evalscope_cli" / ".openclaw-eval"
        os.environ.setdefault("OPENCLAW_EVAL_STATE_DIR", str(state_root / "context-index-state"))
        os.environ.setdefault("OPENCLAW_EVAL_SECRET_DIR", str(state_root / "context-index-secrets"))
        Path(os.environ["OPENCLAW_EVAL_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
        Path(os.environ["OPENCLAW_EVAL_SECRET_DIR"]).mkdir(parents=True, exist_ok=True)
    elif planner_enabled:
        state_root = Path.cwd() / "openclaw_evalscope_cli" / ".openclaw-eval"
        os.environ.setdefault("OPENCLAW_EVAL_STATE_DIR", str(state_root / "planner-state"))
        os.environ.setdefault("OPENCLAW_EVAL_SECRET_DIR", str(state_root / "planner-secrets"))
        Path(os.environ["OPENCLAW_EVAL_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
        Path(os.environ["OPENCLAW_EVAL_SECRET_DIR"]).mkdir(parents=True, exist_ok=True)

    default_compose_project = "openclaw-eval-baseline"
    if router_enabled:
        default_compose_project = "openclaw-eval-router"
    elif context_index_enabled:
        default_compose_project = "openclaw-eval-context-index"
    elif planner_enabled:
        default_compose_project = "openclaw-eval-planner"
    agent_config = _deep_merge(
        {
            "mode": "external",
            "framework": FRAMEWORK_NAME,
            "environment": os.getenv("EVALSCOPE_AGENT_ENVIRONMENT", "local"),
            "bridge": {
                "proxy_host": os.getenv("EVALSCOPE_BRIDGE_PROXY_HOST", "0.0.0.0"),
                "strict_model_routing": router_enabled,
                "model_routes": bridge_routes,
            },
            "timeout": _env_float("EVALSCOPE_AGENT_TIMEOUT", 600.0),
            "kwargs": {
                "compose_project": os.getenv(
                    "OPENCLAW_COMPOSE_PROJECT",
                    default_compose_project,
                ),
                "compose_files": _default_compose_files(),
                "compose_dir": os.getenv("OPENCLAW_COMPOSE_DIR") or None,
                "gateway_service": os.getenv("OPENCLAW_GATEWAY_SERVICE", "openclaw-gateway"),
                "cli_service": os.getenv("OPENCLAW_CLI_SERVICE", "openclaw-cli"),
                "agent_id": os.getenv("OPENCLAW_AGENT_ID", "main"),
                "protocol": os.getenv("OPENCLAW_EVAL_PROTOCOL", "responses"),
                "router_enabled": router_enabled,
                "router_service": os.getenv("OPENCLAW_ROUTER_SERVICE", "openclaw-router-api"),
                "router_endpoint": os.getenv(
                    "OPENCLAW_ROUTER_ENDPOINT", "http://openclaw-router-api:3000"
                ),
                "router_entry_model": os.getenv("OPENCLAW_ROUTER_ENTRY_MODEL", "router-entry"),
                "router_tiers": router_tiers,
                "router_models": router_models,
                "router_confidence_threshold": _env_float("OPENCLAW_ROUTER_CONFIDENCE_THRESHOLD", 0.5),
                "router_request_timeout_ms": _env_int("OPENCLAW_ROUTER_REQUEST_TIMEOUT_MS", 5000),
                "router_strict": _env_bool("OPENCLAW_ROUTER_STRICT", True),
                "router_collect_metrics": _env_bool("OPENCLAW_ROUTER_COLLECT_METRICS", True),
                "context_index_enabled": context_index_enabled,
                "context_index_plugin_id": os.getenv("OPENCLAW_CONTEXT_INDEX_PLUGIN_ID", "context-index"),
                "context_index_plugin_path": os.getenv(
                    "OPENCLAW_CONTEXT_INDEX_PLUGIN_PATH", "/opt/openclaw-plugins/context-index"
                ),
                "context_index_config": context_index_config,
                "context_index_collect_audit": _env_bool("OPENCLAW_CONTEXT_INDEX_COLLECT_AUDIT", True),
                "context_index_audit_limit": _env_int("OPENCLAW_CONTEXT_INDEX_AUDIT_LIMIT", 2000),
                "context_index_reset_per_sample": _env_bool(
                    "OPENCLAW_CONTEXT_INDEX_RESET_PER_SAMPLE", True
                ),
                "context_index_database_path": os.getenv("OPENCLAW_CONTEXT_INDEX_DATABASE_PATH") or None,
                "planner_enabled": planner_enabled,
                "planner_plugin_id": os.getenv("OPENCLAW_PLANNER_PLUGIN_ID", "task-compass"),
                "planner_plugin_path": os.getenv(
                    "OPENCLAW_PLANNER_PLUGIN_PATH", "/opt/openclaw-plugins/task-compass"
                ),
                "planner_config": planner_config,
                "planner_collect_decision": _env_bool("OPENCLAW_PLANNER_COLLECT_DECISION", True),
                "planner_route_script": os.getenv("OPENCLAW_PLANNER_ROUTE_SCRIPT") or None,
                "bridge_host_for_container": os.getenv(
                    "OPENCLAW_BRIDGE_HOST_FOR_CONTAINER", "host.docker.internal"
                ),
                "auto_up": _env_bool("OPENCLAW_AUTO_UP", True),
                "clean_workspace": _env_bool("OPENCLAW_CLEAN_WORKSPACE", True),
                "workspace_path": os.getenv("OPENCLAW_WORKSPACE_PATH", "/home/node/.openclaw/workspace"),
                "preserve_workspace_git": _env_bool("OPENCLAW_PRESERVE_WORKSPACE_GIT", True),
                "workspace_preserve_extra_entries": _env_list("OPENCLAW_WORKSPACE_PRESERVE_EXTRA_ENTRIES"),
                "workspace_clean_timeout_s": _env_float("OPENCLAW_WORKSPACE_CLEAN_TIMEOUT", 60.0),
            },
        },
        _env_json_object("EVALSCOPE_AGENT_CONFIG") or {},
    )

    cfg: dict[str, Any] = {
        "model": model_name,
        "model_id": os.getenv(
            "EVALSCOPE_MODEL_ID",
            (
                "openclaw_router_harness"
                if router_enabled
                else "openclaw_context_index_harness"
                if context_index_enabled
                else "openclaw_planner_harness"
                if planner_enabled
                else "openclaw_cli_harness"
            ),
        ),
        "eval_type": eval_type,
        "datasets": datasets,
        "dataset_args": dataset_args,
        "limit": _env_number("EVALSCOPE_LIMIT", 1),
        "eval_batch_size": _env_int("EVALSCOPE_BATCH_SIZE", 1),
        "generation_config": generation_config,
        "agent_config": agent_config,
        "judge_strategy": os.getenv("EVALSCOPE_JUDGE_STRATEGY", "auto"),
        "judge_model_args": judge_model_args,
        "analysis_report": _env_bool("EVALSCOPE_ANALYSIS_REPORT", False),
        "collect_perf": _env_bool("EVALSCOPE_COLLECT_PERF", True),
        "debug": _env_bool("EVALSCOPE_DEBUG", False),
        "seed": _env_int("EVALSCOPE_SEED", 42),
        "ignore_errors": _env_bool("EVALSCOPE_IGNORE_ERRORS", False),
        "rerun_review": _env_bool("EVALSCOPE_RERUN_REVIEW", False),
        "no_timestamp": _env_bool("EVALSCOPE_NO_TIMESTAMP", False),
        "enable_progress_tracker": _env_bool("EVALSCOPE_ENABLE_PROGRESS_TRACKER", False),
    }
    if router_enabled and cfg["eval_batch_size"] != 1:
        raise ValueError("OpenClaw router v1 requires EVALSCOPE_BATCH_SIZE=1")
    if context_index_enabled and cfg["eval_batch_size"] != 1:
        raise ValueError("OpenClaw Context Index v1 requires EVALSCOPE_BATCH_SIZE=1")
    if planner_enabled and cfg["eval_batch_size"] != 1:
        raise ValueError("OpenClaw Planner v1 requires EVALSCOPE_BATCH_SIZE=1")

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

    use_cache = os.getenv("EVALSCOPE_USE_CACHE")
    if use_cache:
        cfg["use_cache"] = use_cache

    judge_worker_num = os.getenv("EVALSCOPE_JUDGE_WORKER_NUM")
    if judge_worker_num:
        cfg["judge_worker_num"] = int(judge_worker_num)

    work_dir = os.getenv("EVALSCOPE_WORK_DIR")
    if work_dir:
        cfg["work_dir"] = work_dir

    task_config_override = _env_json_object("EVALSCOPE_TASK_CONFIG")
    if task_config_override:
        cfg = _deep_merge(cfg, task_config_override)

    if not cfg.get("work_dir"):
        cfg["work_dir"] = _default_work_dir(cfg)

    return cfg


def main() -> None:
    task_config = parse_task_config(build_task_config())
    started_at = datetime.now(timezone.utc)
    try:
        run_task(task_config)
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        report_path = generate_experiment_report(
            task_config=task_config,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            error=exc,
        )
        print(f"Experiment JSON report: {report_path}")
        raise
    else:
        finished_at = datetime.now(timezone.utc)
        report_path = generate_experiment_report(
            task_config=task_config,
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
        )
        print(f"Experiment JSON report: {report_path}")


if __name__ == "__main__":
    main()
