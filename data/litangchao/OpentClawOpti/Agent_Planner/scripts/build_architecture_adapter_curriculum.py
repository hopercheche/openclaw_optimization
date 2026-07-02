#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLEAN_TRAIN = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_native_compact_train.jsonl"
DEFAULT_ADAPTER_PACK = AGENT_PLANNER_ROOT / "processed" / "stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl"
DEFAULT_OUTPUT = AGENT_PLANNER_ROOT / "processed" / "stage18_architecture_policy_adapter_curriculum_2k.jsonl"
DEFAULT_CLEAN_QUOTAS = {
    "next_subtask": 1200,
    "await_human": 250,
    "replan": 150,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a clean-anchored architecture-policy adapter curriculum. "
            "This counteracts ToolMaze-only over-conservatism by mixing native "
            "next_subtask anchors with a smaller hard-negative slice."
        ),
    )
    parser.add_argument("--clean-train", type=Path, default=DEFAULT_CLEAN_TRAIN)
    parser.add_argument("--adapter-pack", type=Path, default=DEFAULT_ADAPTER_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--clean-next-subtask", type=int, default=DEFAULT_CLEAN_QUOTAS["next_subtask"])
    parser.add_argument("--clean-await-human", type=int, default=DEFAULT_CLEAN_QUOTAS["await_human"])
    parser.add_argument("--clean-replan", type=int, default=DEFAULT_CLEAN_QUOTAS["replan"])
    parser.add_argument("--adapter-rows", type=int, default=400)
    args = parser.parse_args()

    summary = build_curriculum(
        clean_train_path=args.clean_train,
        adapter_pack_path=args.adapter_pack,
        output_path=args.output,
        summary_output_path=args.summary_output,
        clean_quotas={
            "next_subtask": args.clean_next_subtask,
            "await_human": args.clean_await_human,
            "replan": args.clean_replan,
        },
        adapter_rows=args.adapter_rows,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_curriculum(
    *,
    clean_train_path: Path,
    adapter_pack_path: Path,
    output_path: Path,
    summary_output_path: Path | None = None,
    clean_quotas: dict[str, int] | None = None,
    adapter_rows: int = 400,
) -> dict[str, Any]:
    clean_quotas = clean_quotas or dict(DEFAULT_CLEAN_QUOTAS)
    if adapter_rows < 0:
        raise ValueError("adapter_rows must be non-negative.")
    if any(value < 0 for value in clean_quotas.values()):
        raise ValueError("clean quotas must be non-negative.")

    clean_rows = read_jsonl(clean_train_path)
    adapter_pack_rows = read_jsonl(adapter_pack_path)
    selected: list[tuple[str, dict[str, Any]]] = []
    selected.extend(("clean_anchor", row) for row in select_clean_anchors(clean_rows, clean_quotas))
    selected.extend(("toolmaze_adapter", row) for row in select_adapter_rows(adapter_pack_rows, adapter_rows))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = new_summary(
        clean_train_path=clean_train_path,
        adapter_pack_path=adapter_pack_path,
        output_path=output_path,
        clean_rows_seen=len(clean_rows),
        adapter_rows_seen=len(adapter_pack_rows),
        clean_quotas=clean_quotas,
        adapter_rows_requested=adapter_rows,
    )
    with output_path.open("w", encoding="utf-8") as handle:
        for line_number, (mix, row) in enumerate(selected, start=1):
            adapted = adapt_row(row, mix=mix, line_number=line_number)
            handle.write(json.dumps(adapted, ensure_ascii=False, separators=(",", ":")) + "\n")
            update_summary(summary, adapted)

    summary = finalize_summary(summary)
    summary_output = summary_output_path or output_path.with_suffix(output_path.suffix + ".summary.json")
    summary["summary_output"] = str(summary_output)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def select_clean_anchors(rows: list[dict[str, Any]], quotas: dict[str, int]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    for next_action, quota in quotas.items():
        if quota <= 0:
            continue
        picked = 0
        for index, row in enumerate(rows):
            if index in used_ids or expected_next_action(row) != next_action:
                continue
            selected.append(row)
            used_ids.add(index)
            picked += 1
            if picked >= quota:
                break
    return selected


def select_adapter_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
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


def adapt_row(row: dict[str, Any], *, mix: str, line_number: int) -> dict[str, Any]:
    adapted = dict(row)
    adapted["original_source"] = row.get("source")
    adapted["original_source_mode"] = row.get("source_mode")
    adapted["original_line_number"] = row.get("line_number")
    adapted["source"] = "openclaw_architecture_adapter_curriculum"
    adapted["source_mode"] = "stage18_architecture_adapter_curriculum"
    adapted["curriculum_stage"] = "stage18"
    adapted["curriculum_mix"] = mix
    adapted["line_number"] = line_number
    adapted["adapter_weight"] = adapter_weight(row, mix)
    adapted["balance_stratum"] = (
        f"stage18_curriculum|mix={mix}|"
        f"type={perturbation_type(row)}|next={expected_next_action(row)}"
    )
    return adapted


def adapter_weight(row: dict[str, Any], mix: str) -> float:
    if mix == "clean_anchor":
        return 0.9 if expected_next_action(row) == "next_subtask" else 1.0
    if expected_changed(row):
        return 1.1
    return 1.0


def new_summary(
    *,
    clean_train_path: Path,
    adapter_pack_path: Path,
    output_path: Path,
    clean_rows_seen: int,
    adapter_rows_seen: int,
    clean_quotas: dict[str, int],
    adapter_rows_requested: int,
) -> dict[str, Any]:
    return {
        "created_at": utc_now(),
        "clean_train": str(clean_train_path),
        "adapter_pack": str(adapter_pack_path),
        "output": str(output_path),
        "clean_rows_seen": clean_rows_seen,
        "adapter_rows_seen": adapter_rows_seen,
        "clean_quotas": clean_quotas,
        "adapter_rows_requested": adapter_rows_requested,
        "rows_written": 0,
        "curriculum_mix_counts": Counter(),
        "perturbation_type_counts": Counter(),
        "expected_next_action_counts": Counter(),
        "expected_changed_counts": Counter(),
        "tool_counts": Counter(),
        "balance_stratum_counts": Counter(),
    }


def update_summary(summary: dict[str, Any], row: dict[str, Any]) -> None:
    summary["rows_written"] += 1
    summary["curriculum_mix_counts"][row.get("curriculum_mix") or "unknown"] += 1
    summary["perturbation_type_counts"][perturbation_type(row)] += 1
    summary["expected_next_action_counts"][expected_next_action(row)] += 1
    summary["expected_changed_counts"][str(expected_changed(row)).lower()] += 1
    summary["tool_counts"][tool_name(row)] += 1
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
                raise ValueError(f"{path}:{line_number} must be a JSON object.")
            rows.append(row)
    return rows


def expected_next_action(row: dict[str, Any]) -> str:
    expected = row.get("expected") if isinstance(row.get("expected"), dict) else {}
    return str(
        expected.get("next_action")
        or expected.get("verifier_next_action")
        or row.get("next_action")
        or row.get("expected_next_action")
        or "unknown"
    )


def perturbation_type(row: dict[str, Any]) -> str:
    value = row.get("perturbation_type")
    if isinstance(value, str) and value:
        return value
    perturbation = row.get("perturbation")
    if isinstance(perturbation, dict) and isinstance(perturbation.get("type"), str):
        return perturbation["type"]
    return "clean_anchor"


def expected_changed(row: dict[str, Any]) -> bool:
    value = row.get("expected_changed")
    if isinstance(value, bool):
        return value
    perturbation = row.get("perturbation")
    if isinstance(perturbation, dict) and isinstance(perturbation.get("expected_changed"), bool):
        return perturbation["expected_changed"]
    return bool(row.get("raw_prediction") and row.get("teacher_prediction"))


def tool_name(row: dict[str, Any]) -> str:
    value = row.get("tool_name")
    if isinstance(value, str) and value:
        return value
    text = row.get("text")
    if not isinstance(text, str):
        return "unknown"
    marker = '"tool_name":"'
    if marker in text:
        return text.split(marker, 1)[1].split('"', 1)[0]
    return "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
