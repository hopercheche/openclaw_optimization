#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_PLANNER_ROOT.parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from architecture_policy import (  # noqa: E402
    POLICY_FIELDS,
    expected_policy_from_runtime,
    policy_from_tool_context,
    score_compact_policy,
)


DEFAULT_INPUT_ROOT = AGENT_PLANNER_ROOT / "eval_runs" / "20260630T_architecture_full_r1"
DEFAULT_OUTPUT_DIR = AGENT_PLANNER_ROOT / "eval_runs" / "architecture_policy_shadow"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a task-level shadow evaluation for the architecture-policy wrapper. "
            "The wrapper is evaluated on LocalAuditPlanner architecture events without replacing runtime planning."
        ),
    )
    parser.add_argument("--input-root", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument(
        "--disable-next-action-priors",
        action="store_true",
        help="Disable deterministic next_action priors while keeping model/context/executor tool priors.",
    )
    args = parser.parse_args()

    metrics = evaluate_shadow_policy(
        input_roots=args.input_root or [DEFAULT_INPUT_ROOT],
        output_dir=args.output_dir,
        max_rows=args.max_rows,
        apply_next_action_priors=not args.disable_next_action_priors,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def evaluate_shadow_policy(
    *,
    input_roots: list[Path],
    output_dir: Path,
    max_rows: int = 0,
    apply_next_action_priors: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "shadow_predictions.jsonl"
    event_paths = _find_event_paths(input_roots)

    stats: Counter[str] = Counter()
    field_correct: Counter[str] = Counter()
    field_total: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    by_tool: dict[str, Counter[str]] = {}
    by_permission_mode: dict[str, Counter[str]] = {}

    with predictions_path.open("w", encoding="utf-8") as output_handle:
        for events_path in event_paths:
            if max_rows and stats["rows"] >= max_rows:
                break
            stats["event_files_seen"] += 1
            events = _load_jsonl(events_path)
            state = _load_json(events_path.with_name("state.json")) or {}
            task_queue = _task_queue(events)
            if not task_queue:
                stats["event_files_without_task_queue"] += 1
                continue
            for subtask in task_queue:
                if max_rows and stats["rows"] >= max_rows:
                    break
                subtask_id = str(subtask.get("task_id") or "")
                verifier = _first_event(events, "verifier_result", subtask_id=subtask_id)
                expected = expected_policy_from_runtime(subtask, verifier)
                prediction, rules = policy_from_tool_context(
                    tool_name=str(subtask.get("tool_name") or "planner"),
                    permission_mode=_permission_mode(state),
                    task_id=subtask_id or "unknown",
                    action=str(subtask.get("action") or ""),
                    apply_next_action_priors=apply_next_action_priors,
                )
                score = score_compact_policy(prediction, expected)
                stats["rows"] += 1
                if score["exact_match"]:
                    stats["exact_matches"] += 1
                for field, matched in score["matches"].items():
                    field_total[field] += 1
                    if matched:
                        field_correct[field] += 1
                for rule in rules:
                    rule_counts[rule] += 1
                _update_group(by_tool, expected["tool_name"], score)
                _update_group(by_permission_mode, _permission_mode(state), score)
                output_handle.write(json.dumps({
                    "events_path": str(events_path),
                    "run_id": state.get("run_id") or events_path.parent.name,
                    "task_id": source_task_id(events_path),
                    "permission_mode": _permission_mode(state),
                    "subtask_id": subtask_id,
                    "prediction": prediction,
                    "expected": expected,
                    "matches": score["matches"],
                    "exact_match": score["exact_match"],
                    "wrapper_rules": rules,
                }, ensure_ascii=False, separators=(",", ":")) + "\n")

    metrics = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_roots": [str(path) for path in input_roots],
        "output_dir": str(output_dir),
        "predictions_jsonl": str(predictions_path),
        "apply_next_action_priors": apply_next_action_priors,
        "overall": _finalize_counter(stats, field_correct, field_total),
        "rule_counts": dict(sorted(rule_counts.items())),
        "by_tool": _finalize_groups(by_tool),
        "by_permission_mode": _finalize_groups(by_permission_mode),
    }
    metrics_path = output_dir / "metrics.json"
    report_path = output_dir / "report.md"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(_render_report(metrics), encoding="utf-8")
    metrics["outputs"] = {
        "metrics_json": str(metrics_path),
        "report_md": str(report_path),
    }
    return metrics


def _find_event_paths(input_roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in input_roots:
        if root.is_file() and root.name == "events.jsonl":
            candidates = [root]
        elif root.exists():
            candidates = sorted(root.rglob("events.jsonl"))
        else:
            candidates = []
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(path)
    return sorted(paths)


def _task_queue(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    event = _first_event(events, "task_queue_created")
    queue = (event or {}).get("data", {}).get("task_queue")
    return list(queue) if isinstance(queue, list) else []


def _first_event(
    events: list[dict[str, Any]],
    event_type: str,
    *,
    subtask_id: str | None = None,
) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_type") != event_type:
            continue
        if subtask_id is not None and event.get("data", {}).get("subtask_id") != subtask_id:
            continue
        return event
    return None


def _permission_mode(state: dict[str, Any]) -> str:
    return str(state.get("permission_mode") or "DEFAULT").upper()


def source_task_id(events_path: Path) -> str:
    parts = events_path.parts
    if "artifacts" not in parts:
        return ""
    index = parts.index("artifacts")
    return parts[index + 2] if len(parts) > index + 2 else ""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _update_group(groups: dict[str, Counter[str]], key: str, score: dict[str, Any]) -> None:
    group = groups.setdefault(key or "__missing__", Counter())
    group["rows"] += 1
    if score["exact_match"]:
        group["exact_matches"] += 1
    for field, matched in score["matches"].items():
        group[f"{field}_total"] += 1
        if matched:
            group[f"{field}_correct"] += 1


def _finalize_counter(
    stats: Counter[str],
    field_correct: Counter[str],
    field_total: Counter[str],
) -> dict[str, Any]:
    rows = stats["rows"]
    output: dict[str, Any] = {
        "event_files_seen": stats["event_files_seen"],
        "event_files_without_task_queue": stats["event_files_without_task_queue"],
        "rows": rows,
        "exact_matches": stats["exact_matches"],
        "exact_match_rate": round(stats["exact_matches"] / rows, 4) if rows else 0.0,
    }
    for field in POLICY_FIELDS:
        total = field_total[field]
        correct = field_correct[field]
        output[f"{field}_correct"] = correct
        output[f"{field}_total"] = total
        output[f"{field}_accuracy"] = round(correct / total, 4) if total else 0.0
    return output


def _finalize_groups(groups: dict[str, Counter[str]]) -> dict[str, dict[str, Any]]:
    finalized: dict[str, dict[str, Any]] = {}
    for key, counter in sorted(groups.items()):
        rows = counter["rows"]
        item: dict[str, Any] = {
            "rows": rows,
            "exact_matches": counter["exact_matches"],
            "exact_match_rate": round(counter["exact_matches"] / rows, 4) if rows else 0.0,
        }
        for field in POLICY_FIELDS:
            total = counter[f"{field}_total"]
            correct = counter[f"{field}_correct"]
            item[f"{field}_accuracy"] = round(correct / total, 4) if total else 0.0
        finalized[key] = item
    return finalized


def _render_report(metrics: dict[str, Any]) -> str:
    overall = metrics["overall"]
    lines = [
        "# Architecture Policy Shadow Benchmark",
        "",
        f"- Input roots: {', '.join(metrics['input_roots'])}",
        f"- Rows: {overall['rows']}",
        f"- Exact policy match: {overall['exact_match_rate']:.2%}",
        f"- Model tier: {overall['model_tier_accuracy']:.2%}",
        f"- Next action: {overall['verifier_next_action_accuracy']:.2%}",
        f"- Context policy: {overall['context_policy_accuracy']:.2%}",
        f"- Executor kind: {overall['executor_kind_accuracy']:.2%}",
        "",
        "## Rule Counts",
        "",
    ]
    if metrics["rule_counts"]:
        for rule, count in sorted(metrics["rule_counts"].items()):
            lines.append(f"- `{rule}`: {count}")
    else:
        lines.append("- No wrapper rules fired.")
    lines.extend(["", "## By Permission Mode", ""])
    lines.append("| Permission | Rows | Exact | Model | Next | Context | Executor |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for key, item in metrics["by_permission_mode"].items():
        lines.append(
            f"| {key} | {item['rows']} | {item['exact_match_rate']:.2%} | "
            f"{item['model_tier_accuracy']:.2%} | {item['verifier_next_action_accuracy']:.2%} | "
            f"{item['context_policy_accuracy']:.2%} | {item['executor_kind_accuracy']:.2%} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
