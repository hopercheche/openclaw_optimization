#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from evaluate_planner_sft import command_tokens, parse_planner_json, score_schema, token_jaccard, utc_now, write_jsonl
from planner_quality import command_quality_features, summarize_quality_metrics


FINAL_CHECK_HINTS = (
    "json.tool",
    "jq .",
    "echo 'json is valid'",
    'echo "json is valid"',
    "echo 'task completed",
    'echo "task completed',
    "ls -l",
    "test -f",
    "wc -l",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate deterministic post-processing guards for planner generations.")
    parser.add_argument("--generations", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=["complete-final-check-empty", "complete-any-command-empty"],
        default="complete-final-check-empty",
    )
    parser.add_argument("--long-command-chars", type=int, default=120)
    args = parser.parse_args()

    rows = load_jsonl(args.generations)
    processed_rows = [
        postprocess_row(row, mode=args.mode, long_command_chars=args.long_command_chars)
        for row in rows
    ]
    metrics = {
        "created_at": utc_now(),
        "generations": str(args.generations),
        "mode": args.mode,
        "long_command_chars": args.long_command_chars,
        "baseline": summarize(rows, long_command_chars=args.long_command_chars),
        "postprocessed": summarize(processed_rows, long_command_chars=args.long_command_chars),
        "changed_rows": sum(1 for row in processed_rows if row.get("postprocess_changed")),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "postprocessed_generations.jsonl", processed_rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def postprocess_row(row: dict[str, Any], *, mode: str, long_command_chars: int) -> dict[str, Any]:
    parsed = parse_planner_json(row.get("generated_text", ""))
    if not parsed:
        return dict(row, postprocess_changed=False, postprocess_reason=None)
    schema = row.get("schema") if isinstance(row.get("schema"), dict) else score_schema(parsed)
    quality = command_quality_features(parsed, schema=schema, long_command_chars=long_command_chars)
    should_empty = False
    reason = None
    if parsed.get("task_complete") is True and quality.get("command_count", 0) > 0:
        commands = extract_commands(parsed)
        if mode == "complete-any-command-empty":
            should_empty = True
            reason = "complete_any_command"
        elif all(is_final_check_command(command) for command in commands):
            should_empty = True
            reason = "complete_final_check"
    if not should_empty:
        return dict(row, postprocess_changed=False, postprocess_reason=None)

    updated = json.loads(json.dumps(parsed, ensure_ascii=False))
    updated["commands"] = []
    updated_text = json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "<|im_end|>"
    expected_tokens = set(row.get("expected_commands") or [])
    predicted_tokens = command_tokens(updated)
    updated_schema = score_schema(updated)
    updated_quality = command_quality_features(updated, schema=updated_schema, long_command_chars=long_command_chars)
    output = dict(row)
    output.update({
        "generated_text": updated_text,
        "parsed_postprocessed": updated,
        "schema": updated_schema,
        "command_quality": updated_quality,
        "predicted_commands": sorted(predicted_tokens),
        "command_overlap": round(token_jaccard(expected_tokens, predicted_tokens), 4),
        "postprocess_changed": True,
        "postprocess_reason": reason,
    })
    return output


def extract_commands(parsed: dict[str, Any]) -> list[str]:
    commands = []
    for command in parsed.get("commands") or []:
        if not isinstance(command, dict):
            continue
        keystrokes = command.get("keystrokes")
        if isinstance(keystrokes, str):
            commands.append(keystrokes)
    return commands


def is_final_check_command(command: str) -> bool:
    lowered = command.strip().lower()
    if any(hint in lowered for hint in FINAL_CHECK_HINTS):
        return True
    if lowered.startswith("cat ") and any(suffix in lowered for suffix in (".json", ".csv", ".txt")):
        return True
    return False


def summarize(rows: list[dict[str, Any]], *, long_command_chars: int) -> dict[str, Any]:
    total = len(rows) or 1
    overlaps = [float(row.get("command_overlap") or 0.0) for row in rows]
    field_scores = [
        float((row.get("schema") or {}).get("required_field_fraction") or 0.0)
        for row in rows
    ]
    quality = summarize_quality_metrics(rows, long_command_chars=long_command_chars)
    seconds = [
        float(row.get("amortized_request_seconds"))
        for row in rows
        if row.get("amortized_request_seconds") is not None
    ]
    return {
        "generation_examples": len(rows),
        "valid_json_rate": round(sum(1 for row in rows if (row.get("schema") or {}).get("valid_json")) / total, 4),
        "schema_valid_rate": round(sum(1 for row in rows if (row.get("schema") or {}).get("schema_valid")) / total, 4),
        "required_field_rate": round(statistics.mean(field_scores) if field_scores else 0.0, 4),
        "command_overlap_mean": round(statistics.mean(overlaps) if overlaps else 0.0, 4),
        "long_command_rate": quality["long_command_rate"],
        "script_like_command_rate": quality["script_like_command_rate"],
        "validation_only_command_rate": quality["validation_only_command_rate"],
        "complete_with_commands_rate": quality["complete_with_commands_rate"],
        "low_progress_probe_command_rate": quality["low_progress_probe_command_rate"],
        "mean_amortized_request_seconds": round(statistics.mean(seconds) if seconds else 0.0, 6),
    }


def render_report(metrics: dict[str, Any]) -> str:
    baseline = metrics["baseline"]
    processed = metrics["postprocessed"]
    return "\n".join([
        "# Agent Planner Postprocess Benchmark",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Mode: `{metrics['mode']}`",
        f"- Changed rows: {metrics['changed_rows']}",
        "",
        "| Route | Schema | Overlap | Long cmd | Script-like | Validation-only | Complete+cmd | Low-progress | Mean sec |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        format_row("baseline", baseline),
        format_row("postprocessed", processed),
    ]) + "\n"


def format_row(label: str, row: dict[str, Any]) -> str:
    return (
        f"| {label} | {row['schema_valid_rate']:.2%} | {row['command_overlap_mean']:.4f} | "
        f"{row['long_command_rate']:.2%} | {row['script_like_command_rate']:.2%} | "
        f"{row['validation_only_command_rate']:.2%} | {row['complete_with_commands_rate']:.2%} | "
        f"{row['low_progress_probe_command_rate']:.2%} | {row['mean_amortized_request_seconds']:.4f}s |"
    )


if __name__ == "__main__":
    main()
