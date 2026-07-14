#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from evaluate_planner_sft import parse_planner_json, utc_now, write_jsonl


VALIDATION_HINTS = (
    "validate",
    "validation",
    "verify",
    "check",
    "sanity",
    "csv.reader",
    "assert",
)
SCRIPT_HINTS = (
    "python -c",
    "python3 -c",
    "cat >",
    "cat <<",
    "EOF",
    "python <<",
    "python3 <<",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze planner generation failure and risk categories.")
    parser.add_argument("--generations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--long-command-chars", type=int, default=120)
    parser.add_argument("--low-overlap-threshold", type=float, default=0.05)
    args = parser.parse_args()

    rows = load_jsonl(args.generations)
    analyzed = [
        analyze_row(
            row,
            long_command_chars=args.long_command_chars,
            low_overlap_threshold=args.low_overlap_threshold,
        )
        for row in rows
    ]
    summary = summarize(analyzed, args)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output, analyzed)
    summary_path = args.summary_output or args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def analyze_row(row: dict[str, Any], *, long_command_chars: int, low_overlap_threshold: float) -> dict[str, Any]:
    parsed = parse_planner_json(row.get("generated_text", ""))
    schema = row.get("schema") or {}
    labels: list[str] = []
    commands = parsed.get("commands", []) if isinstance(parsed, dict) else []
    command_texts = [
        command.get("keystrokes", "")
        for command in commands
        if isinstance(command, dict)
    ]

    if not schema.get("valid_json", parsed is not None):
        labels.append("invalid_json")
    if not schema.get("schema_valid", False):
        labels.append("schema_invalid")
    if row.get("command_overlap", 0.0) < low_overlap_threshold:
        labels.append("low_command_overlap")
    if any(len(command) > long_command_chars for command in command_texts):
        labels.append("long_command")
    if any("\n" in command.strip() for command in command_texts):
        labels.append("multiline_command")
    if any(contains_any(command, SCRIPT_HINTS) for command in command_texts):
        labels.append("script_like_command")
    if command_texts and all(contains_any(command.lower(), VALIDATION_HINTS) for command in command_texts):
        labels.append("validation_only_command")
    if parsed and parsed.get("task_complete") is True and command_texts:
        labels.append("complete_with_commands")
    if parsed and parsed.get("task_complete") is False and not command_texts:
        labels.append("incomplete_without_commands")

    return {
        "original_index": row.get("original_index"),
        "line_number": row.get("line_number"),
        "pass": row.get("pass"),
        "source": row.get("source"),
        "schema_valid": bool(schema.get("schema_valid", False)),
        "command_overlap": row.get("command_overlap", 0.0),
        "new_tokens": row.get("new_tokens"),
        "command_count": len(command_texts),
        "max_command_chars": max((len(command) for command in command_texts), default=0),
        "labels": labels or ["ok"],
        "task_preview": row.get("task_preview"),
        "generated_preview": row.get("generated_text", "")[:500],
    }


def summarize(rows: list[dict[str, Any]], args) -> dict[str, Any]:
    total = len(rows) or 1
    label_counts = Counter(label for row in rows for label in row["labels"])
    command_lengths = [row["max_command_chars"] for row in rows]
    overlaps = [row["command_overlap"] for row in rows]
    return {
        "created_at": utc_now(),
        "generations": str(args.generations),
        "total_rows": len(rows),
        "long_command_chars": args.long_command_chars,
        "low_overlap_threshold": args.low_overlap_threshold,
        "label_counts": dict(sorted(label_counts.items())),
        "label_rates": {
            label: round(count / total, 4)
            for label, count in sorted(label_counts.items())
        },
        "schema_valid_rate": round(sum(1 for row in rows if row["schema_valid"]) / total, 4),
        "low_overlap_rate": round(label_counts.get("low_command_overlap", 0) / total, 4),
        "long_command_rate": round(label_counts.get("long_command", 0) / total, 4),
        "validation_only_command_rate": round(label_counts.get("validation_only_command", 0) / total, 4),
        "mean_command_overlap": round(statistics.mean(overlaps) if overlaps else 0.0, 4),
        "mean_max_command_chars": round(statistics.mean(command_lengths) if command_lengths else 0.0, 4),
        "p95_max_command_chars": percentile(command_lengths, 0.95),
        "worst_examples": [
            {
                "line_number": row["line_number"],
                "labels": row["labels"],
                "command_overlap": row["command_overlap"],
                "max_command_chars": row["max_command_chars"],
                "generated_preview": row["generated_preview"],
            }
            for row in sorted(
                rows,
                key=lambda item: (
                    item["schema_valid"],
                    item["command_overlap"],
                    -item["max_command_chars"],
                ),
            )[:10]
        ],
    }


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[index]


def contains_any(value: str, needles: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(needle.lower() in lowered for needle in needles)


if __name__ == "__main__":
    main()
