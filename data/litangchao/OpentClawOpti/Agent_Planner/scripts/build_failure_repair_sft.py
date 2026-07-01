#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluate_planner_sft import load_examples, parse_planner_json, score_schema, utc_now, write_jsonl
from planner_quality import command_quality_features, failure_labels


DEFAULT_REPAIR_LABELS = (
    "schema_invalid",
    "low_command_overlap",
    "long_command",
    "script_like_command",
    "validation_only_command",
    "low_progress_probe_command",
    "complete_with_commands",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build failure-focused SFT repair data from model generations and original clean targets.",
    )
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--generations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--start-line", type=int, required=True)
    parser.add_argument("--examples", type=int, required=True)
    parser.add_argument(
        "--repair-labels",
        default=",".join(DEFAULT_REPAIR_LABELS),
        help="Comma-separated model-output labels that qualify a row for repair SFT.",
    )
    parser.add_argument("--low-overlap-threshold", type=float, default=0.08)
    parser.add_argument("--long-command-chars", type=int, default=120)
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()

    repair_labels = parse_label_set(args.repair_labels)
    examples = {
        example.line_number: example
        for example in load_examples(args.eval_file, args.start_line, args.examples)
    }
    generation_rows = load_jsonl(args.generations)

    output_rows: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    skip_reasons: Counter[str] = Counter()
    selected_label_counts: Counter[str] = Counter()

    for row in generation_rows:
        line_number = row.get("line_number")
        example = examples.get(line_number)
        if example is None:
            skip_reasons["missing_eval_example"] += 1
            continue
        generated = parse_planner_json(row.get("generated_text", ""))
        generated_schema = row.get("schema") if isinstance(row.get("schema"), dict) else score_schema(generated)
        labels = failure_labels(
            row | {"schema": generated_schema},
            generated,
            long_command_chars=args.long_command_chars,
            low_overlap_threshold=args.low_overlap_threshold,
        )
        matching_labels = sorted(set(labels) & repair_labels)
        if not matching_labels:
            skip_reasons["no_repair_label"] += 1
            continue

        target = example.expected_json
        target_schema = score_schema(target)
        target_quality = command_quality_features(
            target,
            schema=target_schema,
            long_command_chars=args.long_command_chars,
        )
        target_decision = is_clean_target(target_schema, target_quality)
        if not target_decision["keep"]:
            skip_reasons[f"target_{target_decision['reason']}"] += 1
            continue

        text = example.prompt + example.target
        if text in seen_texts:
            skip_reasons["duplicate_text"] += 1
            continue
        seen_texts.add(text)
        selected_label_counts.update(matching_labels)
        output_rows.append({
            "source": "stage10_failure_repair_sft",
            "created_at": utc_now(),
            "line_number": line_number,
            "model_labels": matching_labels,
            "command_overlap": row.get("command_overlap"),
            "model_quality": command_quality_features(
                generated,
                schema=generated_schema,
                long_command_chars=args.long_command_chars,
            ),
            "target_quality": target_quality,
            "text": text,
        })
        if args.max_rows is not None and len(output_rows) >= args.max_rows:
            break

    summary = {
        "created_at": utc_now(),
        "eval_file": str(args.eval_file),
        "generations": str(args.generations),
        "output": str(args.output),
        "start_line": args.start_line,
        "examples": args.examples,
        "repair_labels": sorted(repair_labels),
        "low_overlap_threshold": args.low_overlap_threshold,
        "long_command_chars": args.long_command_chars,
        "output_rows": len(output_rows),
        "selected_label_counts": dict(sorted(selected_label_counts.items())),
        "skip_reasons": dict(sorted(skip_reasons.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output, output_rows)
    summary_path = args.summary_output or args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_label_set(raw_labels: str) -> set[str]:
    return {
        label.strip()
        for label in raw_labels.split(",")
        if label.strip()
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def is_clean_target(schema: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    if not schema.get("schema_valid", False):
        return {"keep": False, "reason": "schema_invalid"}
    for label in (
        "long_command",
        "multiline_command",
        "script_like_command",
        "risky_command",
        "validation_only_command",
        "low_progress_probe_command",
    ):
        if quality.get(label):
            return {"keep": False, "reason": label}
    return {"keep": True, "reason": "clean"}


if __name__ == "__main__":
    main()
