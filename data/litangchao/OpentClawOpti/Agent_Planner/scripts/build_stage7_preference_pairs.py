#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluate_planner_sft import parse_planner_json, score_schema, utc_now, write_jsonl
from planner_quality import command_quality_features, score_candidate


RISK_FEATURES = (
    "long_command",
    "multiline_command",
    "script_like_command",
    "risky_command",
    "validation_only_command",
    "complete_with_commands",
    "incomplete_without_commands",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build stage7 planner preference/SFT rows from verifier-selected generation improvements."
    )
    parser.add_argument("--eval-samples", type=Path, required=True)
    parser.add_argument("--baseline", required=True, help="Baseline generations as LABEL=path.")
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="Candidate generations as LABEL=path. Repeat for medium/reranked outputs.",
    )
    parser.add_argument("--pair-output", type=Path, required=True)
    parser.add_argument("--sft-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--key-field", default="line_number")
    parser.add_argument("--min-overlap-delta", type=float, default=0.02)
    parser.add_argument("--allow-safety-overlap-drop", type=float, default=0.01)
    parser.add_argument(
        "--min-safety-overlap",
        type=float,
        default=0.05,
        help="Safety-only pairs must still have at least this command overlap to avoid clean-looking wrong actions.",
    )
    parser.add_argument("--min-score-delta", type=float, default=4.0)
    parser.add_argument("--long-command-chars", type=int, default=120)
    args = parser.parse_args()

    samples = load_eval_samples(args.eval_samples, key_field=args.key_field)
    baseline_label, baseline_path = parse_spec(args.baseline)
    baseline_rows = load_generations(baseline_path, label=baseline_label, key_field=args.key_field)
    candidate_rows = [
        (label, load_generations(path, label=label, key_field=args.key_field))
        for label, path in (parse_spec(spec) for spec in args.candidate)
    ]

    pair_rows: list[dict[str, Any]] = []
    sft_rows: list[dict[str, Any]] = []
    seen_sft_texts: set[str] = set()
    skip_reasons: Counter[str] = Counter()
    pair_reasons: Counter[str] = Counter()

    for key, baseline in sorted(baseline_rows.items()):
        sample = samples.get(key)
        if sample is None:
            skip_reasons["missing_eval_sample"] += 1
            continue
        baseline_eval = evaluate_row(baseline, long_command_chars=args.long_command_chars)
        for candidate_label, rows_by_key in candidate_rows:
            candidate = rows_by_key.get(key)
            if candidate is None:
                skip_reasons[f"missing_candidate:{candidate_label}"] += 1
                continue
            candidate_eval = evaluate_row(candidate, long_command_chars=args.long_command_chars)
            decision = should_keep_pair(
                baseline_eval,
                candidate_eval,
                min_overlap_delta=args.min_overlap_delta,
                allow_safety_overlap_drop=args.allow_safety_overlap_drop,
                min_safety_overlap=args.min_safety_overlap,
                min_score_delta=args.min_score_delta,
            )
            if not decision["keep"]:
                skip_reasons[decision["reason"]] += 1
                continue
            chosen_text = clean_completion(candidate.get("generated_text", ""))
            rejected_text = clean_completion(baseline.get("generated_text", ""))
            if not chosen_text or chosen_text == rejected_text:
                skip_reasons["empty_or_identical_completion"] += 1
                continue
            pair_reasons[decision["reason"]] += 1
            pair_rows.append({
                "source": "stage7_verifier_pair",
                "created_at": utc_now(),
                "line_number": key,
                "task_preview": sample.get("task_preview") or baseline.get("task_preview"),
                "prompt": sample["prompt"],
                "chosen": chosen_text,
                "rejected": rejected_text,
                "chosen_label": candidate_label,
                "rejected_label": baseline_label,
                "selection_reason": decision["reason"],
                "overlap_delta": decision["overlap_delta"],
                "score_delta": decision["score_delta"],
                "risk_delta": decision["risk_delta"],
                "chosen_metrics": candidate_eval["metrics"],
                "rejected_metrics": baseline_eval["metrics"],
            })
            sft_text = sample["prompt"] + chosen_text
            if sft_text not in seen_sft_texts:
                seen_sft_texts.add(sft_text)
                sft_rows.append({
                    "source": "stage7_verifier_sft",
                    "line_number": key,
                    "candidate_label": candidate_label,
                    "selection_reason": decision["reason"],
                    "text": sft_text,
                })

    summary = {
        "created_at": utc_now(),
        "eval_samples": str(args.eval_samples),
        "baseline": {"label": baseline_label, "path": str(baseline_path)},
        "candidates": [
            {"label": label, "rows": len(rows)}
            for label, rows in candidate_rows
        ],
        "pair_output": str(args.pair_output),
        "sft_output": str(args.sft_output),
        "pair_rows": len(pair_rows),
        "sft_rows": len(sft_rows),
        "pair_reasons": dict(sorted(pair_reasons.items())),
        "skip_reasons": dict(sorted(skip_reasons.items())),
    }

    args.pair_output.parent.mkdir(parents=True, exist_ok=True)
    args.sft_output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.pair_output, pair_rows)
    write_jsonl(args.sft_output, sft_rows)
    summary_path = args.summary_output or args.pair_output.with_suffix(args.pair_output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_spec(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise SystemExit(f"Spec must be LABEL=path, got: {spec}")
    label, raw_path = spec.split("=", 1)
    label = label.strip()
    if not label:
        raise SystemExit(f"Empty label in spec: {spec}")
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise SystemExit(f"Path does not exist: {path}")
    return label, path


def load_eval_samples(path: Path, *, key_field: str) -> dict[Any, dict[str, Any]]:
    rows: dict[Any, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_index, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = row.get(key_field) or row.get("line_number") or line_index
            rows[key] = row
    return rows


def load_generations(path: Path, *, label: str, key_field: str) -> dict[Any, dict[str, Any]]:
    rows: dict[Any, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_index, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = row.get(key_field) or row.get("line_number") or line_index
            row["candidate_label"] = label
            rows[key] = row
    return rows


def evaluate_row(row: dict[str, Any], *, long_command_chars: int) -> dict[str, Any]:
    parsed = parse_planner_json(row.get("generated_text", ""))
    schema = row.get("schema") if isinstance(row.get("schema"), dict) else score_schema(parsed)
    quality = command_quality_features(parsed, schema=schema, long_command_chars=long_command_chars)
    scored = score_candidate(row | {"schema": schema, "command_quality": quality}, parsed)
    risk_score = sum(int(quality.get(feature, False)) for feature in RISK_FEATURES)
    if int(quality.get("command_count", 0)) > 2:
        risk_score += 1
    return {
        "parsed": parsed,
        "schema": schema,
        "quality": quality,
        "score": scored["score"],
        "risk_score": risk_score,
        "metrics": {
            "schema_valid": bool(schema.get("schema_valid", False)),
            "command_overlap": float(row.get("command_overlap") or 0.0),
            "candidate_score": scored["score"],
            "risk_score": risk_score,
            "long_command": bool(quality.get("long_command", False)),
            "script_like_command": bool(quality.get("script_like_command", False)),
            "validation_only_command": bool(quality.get("validation_only_command", False)),
            "max_command_chars": quality.get("max_command_chars", 0),
        },
    }


def should_keep_pair(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    min_overlap_delta: float,
    allow_safety_overlap_drop: float,
    min_safety_overlap: float,
    min_score_delta: float,
) -> dict[str, Any]:
    baseline_metrics = baseline["metrics"]
    candidate_metrics = candidate["metrics"]
    overlap_delta = round(candidate_metrics["command_overlap"] - baseline_metrics["command_overlap"], 4)
    score_delta = round(candidate_metrics["candidate_score"] - baseline_metrics["candidate_score"], 4)
    risk_delta = baseline_metrics["risk_score"] - candidate_metrics["risk_score"]
    if not candidate_metrics["schema_valid"]:
        return keep_result(False, "candidate_schema_invalid", overlap_delta, score_delta, risk_delta)
    if not baseline_metrics["schema_valid"] and candidate_metrics["schema_valid"]:
        return keep_result(True, "schema_repair", overlap_delta, score_delta, risk_delta)
    if overlap_delta >= min_overlap_delta and score_delta >= -min_score_delta:
        return keep_result(True, "overlap_improved", overlap_delta, score_delta, risk_delta)
    if (
        risk_delta > 0
        and candidate_metrics["command_overlap"] >= min_safety_overlap
        and overlap_delta >= -allow_safety_overlap_drop
        and score_delta >= min_score_delta
    ):
        return keep_result(True, "safety_improved", overlap_delta, score_delta, risk_delta)
    return keep_result(False, "insufficient_gain", overlap_delta, score_delta, risk_delta)


def keep_result(keep: bool, reason: str, overlap_delta: float, score_delta: float, risk_delta: int) -> dict[str, Any]:
    return {
        "keep": keep,
        "reason": reason,
        "overlap_delta": overlap_delta,
        "score_delta": score_delta,
        "risk_delta": risk_delta,
    }


def clean_completion(text: str) -> str:
    return text.strip()


if __name__ == "__main__":
    main()
