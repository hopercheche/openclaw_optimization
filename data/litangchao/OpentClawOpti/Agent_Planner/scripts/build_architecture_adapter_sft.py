#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULE_DISTILL = (
    AGENT_PLANNER_ROOT
    / "processed"
    / "stage16_architecture_rule_distill_classifier_1k.jsonl"
)
DEFAULT_PERTURBATIONS = (
    AGENT_PLANNER_ROOT
    / "processed"
    / "stage16_architecture_policy_unsolvable_toolhazard_perturbations_1k.jsonl"
)
DEFAULT_OUTPUT = (
    AGENT_PLANNER_ROOT
    / "processed"
    / "stage17_architecture_policy_adapter_sft_1k.jsonl"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a balanced compact architecture-policy adapter SFT pack by mixing "
            "runtime-shadow rule-distillation corrections with hard-negative perturbations."
        ),
    )
    parser.add_argument("--rule-distill", type=Path, default=DEFAULT_RULE_DISTILL)
    parser.add_argument("--perturbations", type=Path, default=DEFAULT_PERTURBATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--max-rule-rows", type=int, default=200)
    args = parser.parse_args()

    summary = build_adapter_sft(
        rule_distill_path=args.rule_distill,
        perturbations_path=args.perturbations,
        output_path=args.output,
        summary_output_path=args.summary_output,
        max_rows=args.max_rows,
        max_rule_rows=args.max_rule_rows,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_adapter_sft(
    *,
    rule_distill_path: Path,
    perturbations_path: Path,
    output_path: Path,
    summary_output_path: Path | None = None,
    max_rows: int = 1000,
    max_rule_rows: int = 200,
) -> dict[str, Any]:
    if max_rows <= 0:
        raise ValueError("max_rows must be positive.")
    if max_rule_rows < 0:
        raise ValueError("max_rule_rows must be non-negative.")

    rule_rows = read_jsonl(rule_distill_path)
    perturbation_rows = read_jsonl(perturbations_path)
    selected: list[tuple[str, dict[str, Any]]] = []

    rule_quota = min(max_rule_rows, max_rows, len(rule_rows))
    for row in rule_rows[:rule_quota]:
        selected.append(("rule_distillation", row))

    remaining = max_rows - len(selected)
    if remaining > 0:
        selected.extend(
            ("perturbation", row)
            for row in round_robin_by_perturbation_type(perturbation_rows, remaining)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = new_summary(
        rule_distill_path=rule_distill_path,
        perturbations_path=perturbations_path,
        output_path=output_path,
        max_rows=max_rows,
        max_rule_rows=max_rule_rows,
        rule_rows_seen=len(rule_rows),
        perturbation_rows_seen=len(perturbation_rows),
    )

    with output_path.open("w", encoding="utf-8") as handle:
        for output_line_number, (source_mix, row) in enumerate(selected, start=1):
            adapted = adapt_row(row, source_mix=source_mix, output_line_number=output_line_number)
            handle.write(json.dumps(adapted, ensure_ascii=False, separators=(",", ":")) + "\n")
            update_summary(summary, adapted)

    summary_output = summary_output_path or output_path.with_suffix(output_path.suffix + ".summary.json")
    summary["summary_output"] = str(summary_output)
    summary = finalize_summary(summary)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def round_robin_by_perturbation_type(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, deque[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(perturbation_type(row), deque()).append(row)
    selected: list[dict[str, Any]] = []
    active_keys = deque(sorted(grouped))
    while active_keys and len(selected) < limit:
        key = active_keys.popleft()
        bucket = grouped[key]
        if bucket:
            selected.append(bucket.popleft())
        if bucket:
            active_keys.append(key)
    return selected


def adapt_row(row: dict[str, Any], *, source_mix: str, output_line_number: int) -> dict[str, Any]:
    adapted = dict(row)
    adapted["original_source"] = row.get("source")
    adapted["original_source_mode"] = row.get("source_mode")
    adapted["original_line_number"] = row.get("line_number")
    adapted["source"] = "openclaw_architecture_adapter_mix"
    adapted["format"] = row.get("format") or "openclaw_architecture_compact_sft_text"
    adapted["line_number"] = output_line_number
    adapted["source_mix"] = source_mix
    adapted["source_mode"] = "stage17_architecture_adapter_mix"
    adapted["adapter_stage"] = "stage17"
    adapted["adapter_weight"] = adapter_weight(row, source_mix)
    adapted["balance_stratum"] = balance_stratum(row, source_mix)
    return adapted


def adapter_weight(row: dict[str, Any], source_mix: str) -> float:
    if source_mix == "rule_distillation":
        return 1.25
    if expected_changed(row):
        return 1.15
    return 1.0


def balance_stratum(row: dict[str, Any], source_mix: str) -> str:
    return (
        f"stage17_adapter|source={source_mix}|"
        f"type={perturbation_type(row)}|"
        f"next={expected_next_action(row)}|"
        f"changed={str(expected_changed(row)).lower()}"
    )


def new_summary(
    *,
    rule_distill_path: Path,
    perturbations_path: Path,
    output_path: Path,
    max_rows: int,
    max_rule_rows: int,
    rule_rows_seen: int,
    perturbation_rows_seen: int,
) -> dict[str, Any]:
    return {
        "created_at": utc_now(),
        "rule_distill": str(rule_distill_path),
        "perturbations": str(perturbations_path),
        "output": str(output_path),
        "max_rows": max_rows,
        "max_rule_rows": max_rule_rows,
        "rule_rows_seen": rule_rows_seen,
        "perturbation_rows_seen": perturbation_rows_seen,
        "rows_written": 0,
        "source_mix_counts": Counter(),
        "perturbation_type_counts": Counter(),
        "expected_next_action_counts": Counter(),
        "expected_changed_counts": Counter(),
        "tool_counts": Counter(),
        "permission_mode_counts": Counter(),
        "balance_stratum_counts": Counter(),
    }


def update_summary(summary: dict[str, Any], row: dict[str, Any]) -> None:
    summary["rows_written"] += 1
    summary["source_mix_counts"][row.get("source_mix") or "unknown"] += 1
    summary["perturbation_type_counts"][perturbation_type(row)] += 1
    summary["expected_next_action_counts"][expected_next_action(row)] += 1
    summary["expected_changed_counts"][str(expected_changed(row)).lower()] += 1
    summary["tool_counts"][tool_name(row)] += 1
    summary["permission_mode_counts"][permission_mode(row)] += 1
    summary["balance_stratum_counts"][row.get("balance_stratum") or "unknown"] += 1


def finalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    finalized = dict(summary)
    for key, value in list(finalized.items()):
        if isinstance(value, Counter):
            finalized[key] = dict(sorted(value.items()))
    return finalized


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object.")
            rows.append(row)
    return rows


def perturbation_type(row: dict[str, Any]) -> str:
    value = row.get("perturbation_type")
    if isinstance(value, str) and value:
        return value
    perturbation = row.get("perturbation")
    if isinstance(perturbation, dict) and isinstance(perturbation.get("type"), str):
        return perturbation["type"]
    source_mix = row.get("source_mix")
    if source_mix == "rule_distillation" or row.get("teacher"):
        return "rule_distillation"
    return "unknown"


def expected_next_action(row: dict[str, Any]) -> str:
    expected = row.get("expected")
    if isinstance(expected, dict):
        value = expected.get("next_action") or expected.get("verifier_next_action")
        if isinstance(value, str) and value:
            return value
    value = row.get("expected_next_action") or row.get("next_action")
    if isinstance(value, str) and value:
        return value
    compact_target = row.get("compact_target")
    if isinstance(compact_target, dict) and isinstance(compact_target.get("verifier_next_action"), str):
        return compact_target["verifier_next_action"]
    return "unknown"


def expected_changed(row: dict[str, Any]) -> bool:
    perturbation = row.get("perturbation")
    if isinstance(perturbation, dict) and isinstance(perturbation.get("expected_changed"), bool):
        return perturbation["expected_changed"]
    value = row.get("expected_changed")
    if isinstance(value, bool):
        return value
    return bool(row.get("teacher"))


def tool_name(row: dict[str, Any]) -> str:
    value = row.get("tool_name") or row.get("expected_tool_name")
    if isinstance(value, str) and value:
        return value
    compact_target = row.get("compact_target")
    if isinstance(compact_target, dict) and isinstance(compact_target.get("tool_name"), str):
        return compact_target["tool_name"]
    return "unknown"


def permission_mode(row: dict[str, Any]) -> str:
    value = row.get("permission_mode")
    if isinstance(value, str) and value:
        return value
    return "UNKNOWN"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
