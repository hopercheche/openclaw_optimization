from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openclaw.benchmark import (
    BenchmarkRunResult,
    BenchmarkTask,
    PlannerBenchmarkRunner,
    DEFAULT_TASKS_DIR,
    load_tasks,
    parse_strategies,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX_CONFIG = PROJECT_ROOT / "benchmarks" / "model_matrix.example.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "model_matrix"

SECRET_ENV_FRAGMENTS = ("api_key", "authorization", "credential", "secret", "token")
PROVIDER_ENV_KEYS = {
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "OPENCLAW_DEEPSEEK_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENCLAW_OPENAI_BASE_URL",
    "OPENCLAW_OPENAI_MODEL",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "OPENCLAW_DASHSCOPE_MODEL",
}


@dataclass(slots=True)
class ModelMatrixEntry:
    name: str
    runtime: str = "deterministic"
    required_env: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelMatrixEntry":
        name = _normalize_entry_name(str(payload["name"]))
        env = {
            str(key): str(value)
            for key, value in dict(payload.get("env", {})).items()
        }
        _reject_secret_env_overrides(env)
        return cls(
            name=name,
            runtime=str(payload.get("runtime", "deterministic")).strip().lower(),
            required_env=[str(item) for item in payload.get("required_env", [])],
            env=env,
            enabled=bool(payload.get("enabled", True)),
            notes=str(payload.get("notes", "")),
        )

    def safe_dict(self, missing_required_env: list[str] | None = None) -> dict[str, Any]:
        missing = missing_required_env or []
        return {
            "name": self.name,
            "runtime": self.runtime,
            "enabled": self.enabled,
            "required_env": self.required_env,
            "required_env_present": not missing,
            "missing_required_env": missing,
            "env_override_keys": sorted(self.env),
            "notes": self.notes,
        }


@dataclass(slots=True)
class ModelMatrixEntryResult:
    name: str
    runtime: str
    output_dir: str
    task_count: int
    split_counts: dict[str, int]
    required_env_present: bool
    missing_required_env: list[str]
    env_override_keys: list[str]
    as2_status: dict[str, Any]
    summary: dict[str, dict[str, float | int]]
    split_summary: dict[str, dict[str, dict[str, float | int]]]
    stop_criteria: dict[str, Any]
    model_metrics: dict[str, Any]


@dataclass(slots=True)
class ModelMatrixResult:
    created_at: str
    output_dir: str
    config_path: str
    source_task_count: int
    repeat_count: int
    split_filter: str
    strategies: list[str]
    entries: list[ModelMatrixEntryResult]


class PlannerModelMatrixRunner:
    def __init__(
        self,
        tasks: list[BenchmarkTask],
        entries: list[ModelMatrixEntry],
        output_dir: Path,
        strategies: list[str],
        repeat_count: int = 1,
        split_filter: str = "all",
        config_path: Path | None = None,
    ) -> None:
        self.tasks = tasks
        self.entries = [entry for entry in entries if entry.enabled]
        if not self.entries:
            raise ValueError("No enabled model matrix entries")
        self.output_dir = output_dir
        self.strategies = strategies
        self.repeat_count = max(1, repeat_count)
        self.split_filter = split_filter
        self.config_path = config_path
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> ModelMatrixResult:
        entry_results: list[ModelMatrixEntryResult] = []
        for entry in self.entries:
            entry_output_dir = self.output_dir / entry.name
            with _entry_environment(entry) as missing_required_env:
                run_result = PlannerBenchmarkRunner(
                    tasks=self.tasks,
                    strategies=self.strategies,
                    output_dir=entry_output_dir,
                    repeat_count=self.repeat_count,
                    runtime_mode=entry.runtime,
                    split_filter=self.split_filter,
                ).run()
            entry_results.append(_entry_result(entry, run_result, missing_required_env))

        result = ModelMatrixResult(
            created_at=_utc_now(),
            output_dir=str(self.output_dir),
            config_path=str(self.config_path) if self.config_path else "",
            source_task_count=len(self.tasks),
            repeat_count=self.repeat_count,
            split_filter=self.split_filter,
            strategies=self.strategies,
            entries=entry_results,
        )
        self._write_outputs(result)
        return result

    def _write_outputs(self, result: ModelMatrixResult) -> None:
        metrics_path = self.output_dir / "matrix_metrics.json"
        metrics_path.write_text(
            json.dumps(_matrix_result_to_dict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_path = self.output_dir / "matrix_report.md"
        report_path.write_text(_render_matrix_report(result), encoding="utf-8")


def load_matrix_entries(config_path: Path) -> list[ModelMatrixEntry]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    entries_payload = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries_payload, list):
        raise ValueError("Model matrix config must contain an entries list")
    entries = [ModelMatrixEntry.from_dict(item) for item in entries_payload]
    if not entries:
        raise ValueError(f"No model matrix entries found in {config_path}")
    return entries


def make_output_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / stamp


@contextmanager
def _entry_environment(entry: ModelMatrixEntry) -> Iterator[list[str]]:
    touched_keys = set(PROVIDER_ENV_KEYS) | set(entry.required_env) | set(entry.env)
    original = {key: os.environ.get(key) for key in touched_keys}
    missing_required_env = [
        key for key in entry.required_env
        if not original.get(key)
    ]
    try:
        for key in PROVIDER_ENV_KEYS:
            os.environ.pop(key, None)
        for key in entry.required_env:
            value = original.get(key)
            if value:
                os.environ[key] = value
        for key, value in entry.env.items():
            os.environ[key] = value
        yield missing_required_env
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _entry_result(
    entry: ModelMatrixEntry,
    run_result: BenchmarkRunResult,
    missing_required_env: list[str],
) -> ModelMatrixEntryResult:
    return ModelMatrixEntryResult(
        name=entry.name,
        runtime=entry.runtime,
        output_dir=run_result.output_dir,
        task_count=run_result.task_count,
        split_counts=run_result.split_counts,
        required_env_present=not missing_required_env,
        missing_required_env=missing_required_env,
        env_override_keys=sorted(entry.env),
        as2_status=run_result.as2_status,
        summary=run_result.summary,
        split_summary=run_result.split_summary,
        stop_criteria=run_result.stop_criteria,
        model_metrics=_model_metrics(run_result),
    )


def _model_metrics(run_result: BenchmarkRunResult) -> dict[str, Any]:
    by_strategy: dict[str, dict[str, float | int]] = {}
    for strategy in run_result.summary:
        subset = [result for result in run_result.results if result.strategy == strategy]
        by_strategy[strategy] = _aggregate_model_metrics(subset)
    return {
        "overall": _aggregate_model_metrics(run_result.results),
        "by_strategy": by_strategy,
    }


def _aggregate_model_metrics(results: list[Any]) -> dict[str, float | int]:
    total_runs = len(results)
    started = sum(result.model_started_count for result in results)
    produced = sum(result.model_result_count for result in results)
    fallback = sum(result.model_fallback_count for result in results)
    skipped = sum(result.model_skipped_count for result in results)
    return {
        "runs": total_runs,
        "model_started_count": started,
        "model_result_count": produced,
        "model_fallback_count": fallback,
        "model_skipped_count": skipped,
        "model_success_rate": round(produced / started, 4) if started else 0,
        "model_fallback_rate": round(fallback / started, 4) if started else 0,
        "model_skip_rate": round(skipped / total_runs, 4) if total_runs else 0,
    }


def _matrix_result_to_dict(result: ModelMatrixResult) -> dict[str, Any]:
    return {
        "created_at": result.created_at,
        "output_dir": result.output_dir,
        "config_path": result.config_path,
        "source_task_count": result.source_task_count,
        "repeat_count": result.repeat_count,
        "split_filter": result.split_filter,
        "strategies": result.strategies,
        "entries": [asdict(entry) for entry in result.entries],
    }


def _render_matrix_report(result: ModelMatrixResult) -> str:
    lines = [
        "# OpenClaw Planner Model Matrix Report",
        "",
        f"- Created at: {result.created_at}",
        f"- Output dir: `{result.output_dir}`",
        f"- Config path: `{result.config_path}`",
        f"- Source task count: {result.source_task_count}",
        f"- Repeat count: {result.repeat_count}",
        f"- Split filter: {result.split_filter}",
        f"- Strategies: {', '.join(result.strategies)}",
        "",
        "## Matrix Summary",
        "",
        "| Entry | Runtime | Model ready | Missing env | Stop criteria | `audit_astar` success | `greedy_topk` success | Model fallback rate | Model skip rate |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for entry in result.entries:
        audit_success = _strategy_success(entry.summary, "audit_astar")
        greedy_success = _strategy_success(entry.summary, "greedy_topk")
        overall_model = entry.model_metrics["overall"]
        lines.append(
            f"| `{entry.name}` | {entry.runtime} | {entry.as2_status.get('model_ready')} | "
            f"{', '.join(entry.missing_required_env) or '-'} | "
            f"{entry.stop_criteria.get('met')} | {audit_success:.2%} | "
            f"{greedy_success:.2%} | {overall_model['model_fallback_rate']:.2%} | "
            f"{overall_model['model_skip_rate']:.2%} |"
        )

    lines.extend(["", "## Entry Details", ""])
    for entry in result.entries:
        lines.extend([
            f"### {entry.name}",
            "",
            f"- Output dir: `{entry.output_dir}`",
            f"- Runtime: {entry.runtime}",
            f"- Task count: {entry.task_count}",
            f"- Split counts: {entry.split_counts}",
            f"- Required env present: {entry.required_env_present}",
            f"- Missing required env: {entry.missing_required_env}",
            f"- Env override keys: {entry.env_override_keys}",
            f"- AS2 status: model_ready={entry.as2_status.get('model_ready')}, provider={entry.as2_status.get('model_provider')}, model={entry.as2_status.get('default_model')}",
            f"- Model metrics: {entry.model_metrics['overall']}",
            f"- Stop criteria met: {entry.stop_criteria.get('met')}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def _strategy_success(summary: dict[str, dict[str, float | int]], strategy: str) -> float:
    return float(summary.get(strategy, {}).get("success_rate", 0))


def _reject_secret_env_overrides(env: dict[str, str]) -> None:
    forbidden = [
        key for key in env
        if any(fragment in key.lower() for fragment in SECRET_ENV_FRAGMENTS)
    ]
    if forbidden:
        raise ValueError(
            "Secret-like env keys must be referenced via required_env, not stored in env: "
            + ", ".join(sorted(forbidden))
        )


def _normalize_entry_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    if not normalized:
        raise ValueError("Model matrix entry name cannot be empty")
    return normalized[:80]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenClaw planner model matrix benchmarks.")
    parser.add_argument("--config", type=Path, default=DEFAULT_MATRIX_CONFIG)
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--strategies", default="greedy_topk,audit_astar")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--split", choices=["all", "dev", "holdout"], default="holdout")
    args = parser.parse_args()

    strategies = parse_strategies(args.strategies)
    tasks = load_tasks(args.tasks_dir)
    entries = load_matrix_entries(args.config)
    output_dir = args.output_dir or make_output_dir(args.output_root)
    result = PlannerModelMatrixRunner(
        tasks=tasks,
        entries=entries,
        output_dir=output_dir,
        strategies=strategies,
        repeat_count=args.repeats,
        split_filter=args.split,
        config_path=args.config,
    ).run()
    print(json.dumps({
        "output_dir": result.output_dir,
        "config_path": result.config_path,
        "split_filter": result.split_filter,
        "repeat_count": result.repeat_count,
        "strategies": result.strategies,
        "entries": [
            {
                "name": entry.name,
                "runtime": entry.runtime,
                "required_env_present": entry.required_env_present,
                "missing_required_env": entry.missing_required_env,
                "as2_status": entry.as2_status,
                "model_metrics": entry.model_metrics,
                "summary": entry.summary,
                "stop_criteria": entry.stop_criteria,
            }
            for entry in result.entries
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
