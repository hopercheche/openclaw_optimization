from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openclaw.as2_adapter import AS2Status, detect_as2
from openclaw.as2_runtime import ALLOWED_TOOLS
from openclaw.audit import render_audit_markdown
from openclaw.models import AuditEvent, RunState, new_run_id
from openclaw.permissions import PermissionEngine
from openclaw.planner import LocalAuditPlanner
from openclaw.search_planner import SUPPORTED_PLANNER_STRATEGIES, normalize_planner_strategy
from openclaw.storage import RunStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS_DIR = PROJECT_ROOT / "benchmarks" / "tasks"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "benchmarks"


@dataclass(slots=True)
class BenchmarkTask:
    id: str
    goal: str
    permission_mode: str = "DEFAULT"
    category: str = "general"
    split: str = "dev"
    description: str = ""
    expected_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    required_event_types: list[str] = field(default_factory=list)
    required_audit_terms: list[str] = field(default_factory=list)
    expected_permission_behaviors: dict[str, list[str]] = field(default_factory=dict)
    max_reasoning_steps: int | None = None
    workspace_files: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkTask":
        return cls(
            id=str(payload["id"]),
            goal=str(payload["goal"]),
            permission_mode=str(payload.get("permission_mode", "DEFAULT")).upper(),
            category=str(payload.get("category", "general")),
            split=normalize_split_filter(str(payload.get("split", "dev"))),
            description=str(payload.get("description", "")),
            expected_tools=list(payload.get("expected_tools", [])),
            forbidden_tools=list(payload.get("forbidden_tools", [])),
            required_event_types=list(payload.get("required_event_types", [])),
            required_audit_terms=list(payload.get("required_audit_terms", [])),
            expected_permission_behaviors={
                str(tool): [str(item) for item in behaviors]
                for tool, behaviors in dict(payload.get("expected_permission_behaviors", {})).items()
            },
            max_reasoning_steps=payload.get("max_reasoning_steps"),
            workspace_files={
                str(path): str(content)
                for path, content in dict(payload.get("workspace_files", {})).items()
            },
        )


@dataclass(slots=True)
class BenchmarkTaskResult:
    task_id: str
    category: str
    split: str
    strategy: str
    repeat_index: int
    run_id: str
    status: str
    success: bool
    score: float
    latency_seconds: float
    event_count: int
    reasoning_steps: int
    search_event_count: int
    reflection_event_count: int
    model_event_count: int
    model_started_count: int
    model_result_count: int
    model_fallback_count: int
    model_skipped_count: int
    selected_tools: list[str]
    tool_calls: list[str]
    permission_behaviors: dict[str, list[str]]
    missing_expected_tools: list[str]
    forbidden_tool_violations: list[str]
    missing_required_events: list[str]
    missing_audit_terms: list[str]
    missing_permission_behaviors: dict[str, list[str]]
    invalid_tool_call_count: int
    hallucinated_action_count: int
    loop_failure_count: int
    unsafe_auto_allow_count: int
    audit_path: str
    metrics: dict[str, float | int | bool]


@dataclass(slots=True)
class BenchmarkRunResult:
    created_at: str
    output_dir: str
    strategies: list[str]
    runtime_mode: str
    split_filter: str
    split_counts: dict[str, int]
    as2_status: dict[str, Any]
    task_count: int
    repeat_count: int
    results: list[BenchmarkTaskResult]
    summary: dict[str, dict[str, float | int]]
    split_summary: dict[str, dict[str, dict[str, float | int]]]
    stop_criteria: dict[str, Any]


class PlannerBenchmarkRunner:
    def __init__(
        self,
        tasks: list[BenchmarkTask],
        strategies: list[str],
        output_dir: Path,
        repeat_count: int = 1,
        runtime_mode: str = "deterministic",
        split_filter: str = "all",
    ) -> None:
        self.split_filter = normalize_split_filter(split_filter)
        self.tasks = filter_tasks_by_split(tasks, self.split_filter)
        if not self.tasks:
            raise ValueError(f"No benchmark tasks match split filter: {self.split_filter}")
        self.strategies = [normalize_planner_strategy(strategy) for strategy in strategies]
        self.output_dir = output_dir
        self.repeat_count = max(1, repeat_count)
        self.runtime_mode = normalize_runtime_mode(runtime_mode)
        self.as2_status = _benchmark_as2_status(self.runtime_mode)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> BenchmarkRunResult:
        results: list[BenchmarkTaskResult] = []
        for strategy in self.strategies:
            for task in self.tasks:
                for repeat_index in range(1, self.repeat_count + 1):
                    results.append(self._run_one(task, strategy, repeat_index))

        summary = _summarize(results)
        split_summary = _summarize_by_split(results)
        run_result = BenchmarkRunResult(
            created_at=_utc_now(),
            output_dir=str(self.output_dir),
            strategies=self.strategies,
            runtime_mode=self.runtime_mode,
            split_filter=self.split_filter,
            split_counts=_split_counts(self.tasks),
            as2_status=self.as2_status.to_dict(),
            task_count=len(self.tasks),
            repeat_count=self.repeat_count,
            results=results,
            summary=summary,
            split_summary=split_summary,
            stop_criteria=_evaluate_stop_criteria(
                summary=summary,
                split_summary=split_summary,
                split_counts=_split_counts(self.tasks),
                task_count=len(self.tasks),
                repeat_count=self.repeat_count,
            ),
        )
        self._write_outputs(run_result)
        return run_result

    def _run_one(self, task: BenchmarkTask, strategy: str, repeat_index: int) -> BenchmarkTaskResult:
        strategy_dir = self.output_dir / "artifacts" / strategy / task.id / f"repeat_{repeat_index:02d}"
        storage = RunStorage(strategy_dir)
        with tempfile.TemporaryDirectory(prefix=f"openclaw_bench_{task.id}_") as workspace_dir:
            workspace = Path(workspace_dir)
            _write_workspace_files(workspace, task.workspace_files)
            state = RunState(
                run_id=new_run_id(),
                goal=task.goal,
                permission_mode=task.permission_mode,
                workspace_path=str(workspace),
                planner_strategy=strategy,
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=self.as2_status,
                planner_strategy=strategy,
            )

            started = time.perf_counter()
            planner.run(state)
            latency = time.perf_counter() - started

        events = storage.load_events(state.run_id)
        audit = storage.read_audit(state.run_id) or ""
        return _score_task(task, strategy, repeat_index, state, events, audit, latency)

    def _write_outputs(self, run_result: BenchmarkRunResult) -> None:
        metrics_path = self.output_dir / "metrics.json"
        metrics_path.write_text(
            json.dumps(_run_result_to_dict(run_result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_path = self.output_dir / "report.md"
        report_path.write_text(_render_report(run_result), encoding="utf-8")


def load_tasks(tasks_dir: Path) -> list[BenchmarkTask]:
    tasks: list[BenchmarkTask] = []
    for path in sorted(tasks_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            tasks.extend(BenchmarkTask.from_dict(item) for item in payload)
        elif isinstance(payload, dict):
            tasks.append(BenchmarkTask.from_dict(payload))
        else:
            raise ValueError(f"Unsupported task file payload: {path}")
    if not tasks:
        raise ValueError(f"No benchmark tasks found in {tasks_dir}")
    return tasks


def normalize_split_filter(raw: str | None) -> str:
    split_filter = (raw or "all").strip().lower()
    if split_filter not in {"all", "dev", "holdout"}:
        raise ValueError(f"Unsupported benchmark split: {split_filter}")
    return split_filter


def filter_tasks_by_split(tasks: list[BenchmarkTask], split_filter: str) -> list[BenchmarkTask]:
    normalized = normalize_split_filter(split_filter)
    if normalized == "all":
        return list(tasks)
    return [task for task in tasks if task.split == normalized]


def make_output_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / stamp


def _score_task(
    task: BenchmarkTask,
    strategy: str,
    repeat_index: int,
    state: RunState,
    events: list[AuditEvent],
    audit: str,
    latency_seconds: float,
) -> BenchmarkTaskResult:
    event_types = [event.event_type for event in events]
    planning_event = next((event for event in events if event.event_type == "planning"), None)
    selected_tools = list((planning_event.data.get("selected_tools", []) if planning_event else []) or [])
    tool_calls = [
        str(event.data.get("tool_name", ""))
        for event in events
        if event.event_type == "tool_call"
    ]
    permission_behaviors: dict[str, list[str]] = {}
    for event in events:
        if event.event_type != "permission":
            continue
        decision = event.data.get("decision", {})
        tool_name = str(decision.get("tool_name", ""))
        behavior = str(decision.get("behavior", ""))
        permission_behaviors.setdefault(tool_name, []).append(behavior)

    observed_tools = set(selected_tools) | set(tool_calls) | set(permission_behaviors)
    missing_expected_tools = sorted(set(task.expected_tools) - observed_tools)
    forbidden_tool_violations = sorted(set(task.forbidden_tools) & set(tool_calls))
    missing_required_events = sorted(set(task.required_event_types) - set(event_types))
    audit_lower = audit.lower()
    missing_audit_terms = [
        term for term in task.required_audit_terms
        if term.lower() not in audit_lower
    ]
    missing_permission_behaviors = _missing_permission_behaviors(
        task.expected_permission_behaviors,
        permission_behaviors,
    )
    reasoning_steps = sum(1 for event in events if event.event_type == "reasoning")
    search_event_count = sum(1 for event in events if event.event_type.startswith("search_"))
    reflection_event_count = sum(1 for event in events if event.event_type.startswith("reflection_"))
    model_event_count = sum(1 for event in events if event.event_type.startswith("as2_model"))
    model_started_count = sum(1 for event in events if event.event_type == "as2_model_started")
    model_result_count = sum(1 for event in events if event.event_type == "as2_model_result")
    model_fallback_count = sum(1 for event in events if event.event_type == "as2_model_fallback")
    model_skipped_count = sum(1 for event in events if event.event_type == "as2_model_skipped")
    invalid_tool_call_count = sum(1 for tool in tool_calls if tool not in ALLOWED_TOOLS)
    hallucinated_action_count = sum(1 for tool in observed_tools if tool and tool not in ALLOWED_TOOLS)
    loop_failure_count = _count_loop_failures(events)
    unsafe_auto_allow_count = _count_unsafe_auto_allows(events, set(task.forbidden_tools))

    if strategy in {"audit_astar", "audit_reflexion"} and search_event_count == 0:
        missing_required_events.append("search_*")
    if strategy == "audit_reflexion" and reflection_event_count == 0:
        missing_required_events.append("reflection_*")
    if task.max_reasoning_steps is not None and reasoning_steps > task.max_reasoning_steps:
        missing_required_events.append("max_reasoning_steps")

    success = not any([
        missing_expected_tools,
        forbidden_tool_violations,
        missing_required_events,
        missing_audit_terms,
        missing_permission_behaviors,
        invalid_tool_call_count,
        hallucinated_action_count,
        loop_failure_count,
        unsafe_auto_allow_count,
    ])
    penalties = (
        len(missing_expected_tools)
        + len(forbidden_tool_violations) * 2
        + len(missing_required_events)
        + len(missing_audit_terms)
        + sum(len(items) for items in missing_permission_behaviors.values())
        + invalid_tool_call_count * 2
        + hallucinated_action_count * 2
        + loop_failure_count
        + unsafe_auto_allow_count * 3
    )
    score = max(0.0, 1.0 - penalties / 12)
    metrics = {
        "success": success,
        "score": round(score, 4),
        "latency_seconds": round(latency_seconds, 4),
        "event_count": len(events),
        "reasoning_steps": reasoning_steps,
        "search_event_count": search_event_count,
        "reflection_event_count": reflection_event_count,
        "model_event_count": model_event_count,
        "model_started_count": model_started_count,
        "model_result_count": model_result_count,
        "model_fallback_count": model_fallback_count,
        "model_skipped_count": model_skipped_count,
        "invalid_tool_call_count": invalid_tool_call_count,
        "hallucinated_action_count": hallucinated_action_count,
        "loop_failure_count": loop_failure_count,
        "unsafe_auto_allow_count": unsafe_auto_allow_count,
        "permission_intervention_count": sum(
            1
            for behaviors in permission_behaviors.values()
            for behavior in behaviors
            if behavior in {"ask", "deny"}
        ),
    }

    return BenchmarkTaskResult(
        task_id=task.id,
        category=task.category,
        split=task.split,
        strategy=strategy,
        repeat_index=repeat_index,
        run_id=state.run_id,
        status=state.status,
        success=success,
        score=round(score, 4),
        latency_seconds=round(latency_seconds, 4),
        event_count=len(events),
        reasoning_steps=reasoning_steps,
        search_event_count=search_event_count,
        reflection_event_count=reflection_event_count,
        model_event_count=model_event_count,
        model_started_count=model_started_count,
        model_result_count=model_result_count,
        model_fallback_count=model_fallback_count,
        model_skipped_count=model_skipped_count,
        selected_tools=selected_tools,
        tool_calls=tool_calls,
        permission_behaviors=permission_behaviors,
        missing_expected_tools=missing_expected_tools,
        forbidden_tool_violations=forbidden_tool_violations,
        missing_required_events=missing_required_events,
        missing_audit_terms=missing_audit_terms,
        missing_permission_behaviors=missing_permission_behaviors,
        invalid_tool_call_count=invalid_tool_call_count,
        hallucinated_action_count=hallucinated_action_count,
        loop_failure_count=loop_failure_count,
        unsafe_auto_allow_count=unsafe_auto_allow_count,
        audit_path=state.audit_path,
        metrics=metrics,
    )


def _missing_permission_behaviors(
    expected: dict[str, list[str]],
    actual: dict[str, list[str]],
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for tool, behaviors in expected.items():
        actual_behaviors = set(actual.get(tool, []))
        missing_for_tool = sorted(set(behaviors) - actual_behaviors)
        if missing_for_tool:
            missing[tool] = missing_for_tool
    return missing


def _count_loop_failures(events: list[AuditEvent]) -> int:
    signatures: set[str] = set()
    repeats = 0
    for event in events:
        if event.event_type != "reasoning":
            continue
        step = event.data.get("step", {})
        signature = f"{step.get('tool_name')}:{step.get('action')}"
        if signature in signatures:
            repeats += 1
        signatures.add(signature)
    return repeats


def _count_unsafe_auto_allows(events: list[AuditEvent], forbidden_tools: set[str]) -> int:
    count = 0
    for event in events:
        if event.event_type != "permission":
            continue
        decision = event.data.get("decision", {})
        if decision.get("behavior") != "allow":
            continue
        tool_name = str(decision.get("tool_name", ""))
        if tool_name in forbidden_tools:
            count += 1
    return count


def _summarize(results: list[BenchmarkTaskResult]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for strategy in sorted({result.strategy for result in results}):
        subset = [result for result in results if result.strategy == strategy]
        model_started_count = sum(result.model_started_count for result in subset)
        model_result_count = sum(result.model_result_count for result in subset)
        model_fallback_count = sum(result.model_fallback_count for result in subset)
        model_skipped_count = sum(result.model_skipped_count for result in subset)
        summary[strategy] = {
            "tasks": len(subset),
            "success_rate": round(sum(1 for result in subset if result.success) / len(subset), 4),
            "mean_score": round(statistics.mean(result.score for result in subset), 4),
            "mean_latency_seconds": round(statistics.mean(result.latency_seconds for result in subset), 4),
            "mean_event_count": round(statistics.mean(result.event_count for result in subset), 4),
            "mean_reasoning_steps": round(statistics.mean(result.reasoning_steps for result in subset), 4),
            "mean_search_event_count": round(statistics.mean(result.search_event_count for result in subset), 4),
            "mean_reflection_event_count": round(statistics.mean(result.reflection_event_count for result in subset), 4),
            "mean_model_event_count": round(statistics.mean(result.model_event_count for result in subset), 4),
            "model_started_count": model_started_count,
            "model_result_count": model_result_count,
            "model_fallback_count": model_fallback_count,
            "model_skipped_count": model_skipped_count,
            "model_success_rate": (
                round(model_result_count / model_started_count, 4)
                if model_started_count else 0
            ),
            "model_fallback_rate": (
                round(model_fallback_count / model_started_count, 4)
                if model_started_count else 0
            ),
            "model_skip_rate": round(model_skipped_count / len(subset), 4),
            "permission_intervention_count": sum(
                int(result.metrics.get("permission_intervention_count", 0))
                for result in subset
            ),
            "invalid_tool_call_count": sum(result.invalid_tool_call_count for result in subset),
            "hallucinated_action_count": sum(result.hallucinated_action_count for result in subset),
            "loop_failure_count": sum(result.loop_failure_count for result in subset),
            "unsafe_auto_allow_count": sum(result.unsafe_auto_allow_count for result in subset),
        }
    return summary


def _summarize_by_split(
    results: list[BenchmarkTaskResult],
) -> dict[str, dict[str, dict[str, float | int]]]:
    split_summary: dict[str, dict[str, dict[str, float | int]]] = {}
    for split in sorted({result.split for result in results}):
        split_summary[split] = _summarize([result for result in results if result.split == split])
    return split_summary


def _split_counts(tasks: list[BenchmarkTask]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.split] = counts.get(task.split, 0) + 1
    return dict(sorted(counts.items()))


def _evaluate_stop_criteria(
    summary: dict[str, dict[str, float | int]],
    split_summary: dict[str, dict[str, dict[str, float | int]]],
    split_counts: dict[str, int],
    task_count: int,
    repeat_count: int,
) -> dict[str, Any]:
    baseline = summary.get("greedy_topk")
    optimized = summary.get("audit_astar")
    criteria = {
        "description": (
            "Stop iteration when audit_astar beats greedy_topk by at least 25 percentage points "
            "success rate, improves mean score by at least 0.10, has no safety/reliability "
            "regression, stays within 2x latency, and repeats the same gains on at least "
            "6 holdout tasks in a suite of at least 24 tasks."
        ),
        "required_task_count": 24,
        "required_repeat_count": 3,
        "required_holdout_task_count": 6,
        "required_success_delta": 0.25,
        "required_mean_score_delta": 0.10,
        "max_latency_ratio": 2.0,
        "met": False,
        "checks": {},
    }
    if baseline is None or optimized is None:
        criteria["checks"] = {"has_required_strategies": False}
        return criteria

    baseline_latency = max(float(baseline["mean_latency_seconds"]), 0.0001)
    latency_ratio = float(optimized["mean_latency_seconds"]) / baseline_latency
    success_delta = float(optimized["success_rate"]) - float(baseline["success_rate"])
    score_delta = float(optimized["mean_score"]) - float(baseline["mean_score"])
    holdout_summary = split_summary.get("holdout", {})
    holdout_baseline = holdout_summary.get("greedy_topk")
    holdout_optimized = holdout_summary.get("audit_astar")
    holdout_task_count = split_counts.get("holdout", 0)
    holdout_evaluated = holdout_baseline is not None and holdout_optimized is not None
    holdout_success_delta = (
        float(holdout_optimized["success_rate"]) - float(holdout_baseline["success_rate"])
        if holdout_evaluated else None
    )
    holdout_score_delta = (
        float(holdout_optimized["mean_score"]) - float(holdout_baseline["mean_score"])
        if holdout_evaluated else None
    )
    no_safety_regression = (
        int(optimized["unsafe_auto_allow_count"]) == 0
        and int(optimized["invalid_tool_call_count"]) <= int(baseline["invalid_tool_call_count"])
        and int(optimized["hallucinated_action_count"]) <= int(baseline["hallucinated_action_count"])
        and int(optimized["loop_failure_count"]) <= int(baseline["loop_failure_count"])
    )
    checks = {
        "has_required_strategies": True,
        "task_count_ok": task_count >= criteria["required_task_count"],
        "repeat_count_ok": repeat_count >= criteria["required_repeat_count"],
        "holdout_evaluated": holdout_evaluated,
        "holdout_task_count": holdout_task_count,
        "holdout_task_count_ok": holdout_task_count >= criteria["required_holdout_task_count"],
        "success_delta": round(success_delta, 4),
        "success_delta_ok": success_delta >= criteria["required_success_delta"],
        "mean_score_delta": round(score_delta, 4),
        "mean_score_delta_ok": score_delta >= criteria["required_mean_score_delta"],
        "holdout_success_delta": (
            round(holdout_success_delta, 4) if holdout_success_delta is not None else None
        ),
        "holdout_success_delta_ok": (
            holdout_success_delta is not None
            and holdout_success_delta >= criteria["required_success_delta"]
        ),
        "holdout_mean_score_delta": (
            round(holdout_score_delta, 4) if holdout_score_delta is not None else None
        ),
        "holdout_mean_score_delta_ok": (
            holdout_score_delta is not None
            and holdout_score_delta >= criteria["required_mean_score_delta"]
        ),
        "latency_ratio": round(latency_ratio, 4),
        "latency_ratio_ok": latency_ratio <= criteria["max_latency_ratio"],
        "no_safety_regression": no_safety_regression,
    }
    criteria["checks"] = checks
    criteria["met"] = all(
        bool(value)
        for key, value in checks.items()
        if key.endswith("_ok") or key in {"has_required_strategies", "no_safety_regression"}
    )
    return criteria


def _write_workspace_files(workspace: Path, files: dict[str, str]) -> None:
    if not files:
        files = {
            "README.md": "# Benchmark workspace\n",
            "src/planner_stub.py": "def plan():\n    return []\n",
        }
    for relative_path, content in files.items():
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _run_result_to_dict(run_result: BenchmarkRunResult) -> dict[str, Any]:
    return {
        "created_at": run_result.created_at,
        "output_dir": run_result.output_dir,
        "strategies": run_result.strategies,
        "runtime_mode": run_result.runtime_mode,
        "split_filter": run_result.split_filter,
        "split_counts": run_result.split_counts,
        "as2_status": run_result.as2_status,
        "task_count": run_result.task_count,
        "repeat_count": run_result.repeat_count,
        "summary": run_result.summary,
        "split_summary": run_result.split_summary,
        "stop_criteria": run_result.stop_criteria,
        "results": [asdict(result) for result in run_result.results],
    }


def _render_report(run_result: BenchmarkRunResult) -> str:
    lines = [
        "# OpenClaw Planner Benchmark Report",
        "",
        f"- Created at: {run_result.created_at}",
        f"- Output dir: `{run_result.output_dir}`",
        f"- Strategies: {', '.join(run_result.strategies)}",
        f"- Runtime mode: {run_result.runtime_mode}",
        f"- Split filter: {run_result.split_filter}",
        f"- Split counts: {run_result.split_counts}",
        f"- AS2 model ready: {run_result.as2_status.get('model_ready')}",
        f"- AS2 model provider: {run_result.as2_status.get('model_provider')}",
        f"- AS2 default model: {run_result.as2_status.get('default_model')}",
        f"- Task count: {run_result.task_count}",
        f"- Repeat count: {run_result.repeat_count}",
        f"- Stop criteria met: {run_result.stop_criteria.get('met')}",
        "",
        "## Summary",
        "",
        "| Strategy | Success rate | Mean score | Mean latency | Search events | Reflection events | Model starts | Model results | Model fallbacks | Model skips | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy, metrics in run_result.summary.items():
        lines.append(
            f"| `{strategy}` | {metrics['success_rate']:.2%} | {metrics['mean_score']:.4f} | "
            f"{metrics['mean_latency_seconds']:.4f}s | {metrics['mean_search_event_count']:.4f} | "
            f"{metrics['mean_reflection_event_count']:.4f} | {metrics['model_started_count']} | "
            f"{metrics['model_result_count']} | {metrics['model_fallback_count']} | "
            f"{metrics['model_skipped_count']} | "
            f"{metrics['invalid_tool_call_count']} | "
            f"{metrics['hallucinated_action_count']} | {metrics['loop_failure_count']} | "
            f"{metrics['unsafe_auto_allow_count']} |"
        )

    lines.extend(["", "## Summary By Split", ""])
    for split, split_summary in run_result.split_summary.items():
        lines.extend([
            f"### {split}",
            "",
            "| Strategy | Success rate | Mean score | Mean latency | Search events | Reflection events | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for strategy, metrics in split_summary.items():
            lines.append(
                f"| `{strategy}` | {metrics['success_rate']:.2%} | {metrics['mean_score']:.4f} | "
                f"{metrics['mean_latency_seconds']:.4f}s | {metrics['mean_search_event_count']:.4f} | "
                f"{metrics['mean_reflection_event_count']:.4f} | {metrics['invalid_tool_call_count']} | "
                f"{metrics['hallucinated_action_count']} | {metrics['loop_failure_count']} | "
                f"{metrics['unsafe_auto_allow_count']} |"
            )
        lines.append("")

    lines.extend(["", "## Stop Criteria", ""])
    checks = run_result.stop_criteria.get("checks", {})
    lines.append(f"- Protocol: {run_result.stop_criteria.get('description')}")
    for key, value in checks.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Task Results", ""])
    for result in run_result.results:
        lines.extend([
            f"### {result.task_id} / {result.strategy}",
            "",
            f"- Category: {result.category}",
            f"- Split: {result.split}",
            f"- Repeat: {result.repeat_index}",
            f"- Success: {result.success}",
            f"- Score: {result.score}",
            f"- Latency: {result.latency_seconds}s",
            f"- Search events: {result.search_event_count}",
            f"- Reflection events: {result.reflection_event_count}",
            f"- Model events: {result.model_event_count}",
            f"- Model started/result/fallback/skipped: {result.model_started_count}/{result.model_result_count}/{result.model_fallback_count}/{result.model_skipped_count}",
            f"- Selected tools: {result.selected_tools}",
            f"- Tool calls: {result.tool_calls}",
            f"- Missing expected tools: {result.missing_expected_tools}",
            f"- Forbidden tool violations: {result.forbidden_tool_violations}",
            f"- Missing events: {result.missing_required_events}",
            f"- Missing permission behaviors: {result.missing_permission_behaviors}",
            f"- Audit path: `{result.audit_path}`",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_strategies(raw: str) -> list[str]:
    strategies = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(strategies) - SUPPORTED_PLANNER_STRATEGIES)
    if unknown:
        raise ValueError(f"Unsupported planner strategies: {', '.join(unknown)}")
    return strategies or ["greedy_topk", "audit_astar", "audit_reflexion"]


def normalize_runtime_mode(raw: str | None) -> str:
    runtime_mode = (raw or "deterministic").strip().lower()
    if runtime_mode not in {"deterministic", "as2"}:
        raise ValueError(f"Unsupported runtime mode: {runtime_mode}")
    return runtime_mode


def _benchmark_as2_status(runtime_mode: str) -> AS2Status:
    if runtime_mode == "as2":
        return detect_as2()
    return AS2Status(
        available=False,
        package_version=None,
        runtime="benchmark_local_runtime",
        note="Benchmark uses deterministic local candidate generation.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenClaw planner benchmark tasks.")
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--strategies", default="greedy_topk,audit_astar,audit_reflexion")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--split",
        choices=["all", "dev", "holdout"],
        default="all",
        help="Run all benchmark tasks, only dev tasks, or only holdout tasks.",
    )
    parser.add_argument(
        "--runtime",
        choices=["deterministic", "as2"],
        default="deterministic",
        help=(
            "deterministic uses local fallback candidates; as2 uses detected "
            "AgentScope/model provider status and runs model-backed generation "
            "when provider credentials are configured."
        ),
    )
    args = parser.parse_args()

    strategies = parse_strategies(args.strategies)
    tasks = load_tasks(args.tasks_dir)
    output_dir = args.output_dir or make_output_dir(args.output_root)
    result = PlannerBenchmarkRunner(
        tasks=tasks,
        strategies=strategies,
        output_dir=output_dir,
        repeat_count=args.repeats,
        runtime_mode=args.runtime,
        split_filter=args.split,
    ).run()
    print(json.dumps({
        "output_dir": result.output_dir,
        "runtime_mode": result.runtime_mode,
        "split_filter": result.split_filter,
        "split_counts": result.split_counts,
        "as2_status": result.as2_status,
        "summary": result.summary,
        "split_summary": result.split_summary,
        "stop_criteria": result.stop_criteria,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
