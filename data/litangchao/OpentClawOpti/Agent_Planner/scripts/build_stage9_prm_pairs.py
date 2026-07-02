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
    "low_progress_probe_command",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build lower-noise Stage9 PRM-style preference pairs from multiple planner candidates.",
    )
    parser.add_argument("--eval-samples", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="Candidate generations as LABEL=path. Repeat for each candidate source.",
    )
    parser.add_argument("--pair-output", type=Path, required=True)
    parser.add_argument("--sft-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--key-field", default="line_number")
    parser.add_argument("--min-reward-margin", type=float, default=8.0)
    parser.add_argument("--min-overlap-margin", type=float, default=0.05)
    parser.add_argument("--min-chosen-overlap", type=float, default=0.05)
    parser.add_argument("--max-risk-delta", type=float, default=0.0)
    parser.add_argument("--long-command-chars", type=int, default=120)
    args = parser.parse_args()

    samples = load_jsonl_by_key(args.eval_samples, key_field=args.key_field)
    candidate_sets = [
        (label, load_jsonl_by_key(path, key_field=args.key_field))
        for label, path in (parse_spec(spec) for spec in args.candidate)
    ]

    pair_rows: list[dict[str, Any]] = []
    sft_rows: list[dict[str, Any]] = []
    seen_sft_texts: set[str] = set()
    skip_reasons: Counter[str] = Counter()
    pair_sources: Counter[str] = Counter()

    keys = sorted(set().union(*(rows.keys() for _, rows in candidate_sets)))
    for key in keys:
        sample = samples.get(key)
        if sample is None:
            skip_reasons["missing_eval_sample"] += 1
            continue
        scored_candidates = []
        for label, rows_by_key in candidate_sets:
            row = rows_by_key.get(key)
            if row is None:
                continue
            scored = evaluate_row(row, label=label, long_command_chars=args.long_command_chars)
            scored_candidates.append(scored)
        if len(scored_candidates) < 2:
            skip_reasons["too_few_candidates"] += 1
            continue

        scored_candidates.sort(key=lambda item: item["reward"]["total"], reverse=True)
        chosen = scored_candidates[0]
        rejected = scored_candidates[-1]
        decision = should_keep_pair(chosen, rejected, args)
        if not decision["keep"]:
            skip_reasons[decision["reason"]] += 1
            continue

        chosen_text = clean_completion(chosen["row"].get("generated_text", ""))
        rejected_text = clean_completion(rejected["row"].get("generated_text", ""))
        if not chosen_text or not rejected_text or chosen_text == rejected_text:
            skip_reasons["empty_or_identical_completion"] += 1
            continue

        pair_sources[f"{chosen['label']}>{rejected['label']}"] += 1
        pair_rows.append({
            "source": "stage9_prm_pair",
            "created_at": utc_now(),
            "line_number": key,
            "task_preview": sample.get("task_preview") or chosen["row"].get("task_preview"),
            "prompt": sample["prompt"],
            "chosen": chosen_text,
            "rejected": rejected_text,
            "chosen_label": chosen["label"],
            "rejected_label": rejected["label"],
            "selection_reason": decision["reason"],
            "reward_margin": decision["reward_margin"],
            "overlap_delta": decision["overlap_delta"],
            "risk_delta": decision["risk_delta"],
            "chosen_reward": chosen["reward"],
            "rejected_reward": rejected["reward"],
            "chosen_metrics": chosen["metrics"],
            "rejected_metrics": rejected["metrics"],
        })

        sft_text = sample["prompt"] + chosen_text
        if sft_text not in seen_sft_texts:
            seen_sft_texts.add(sft_text)
            sft_rows.append({
                "source": "stage9_prm_sft",
                "line_number": key,
                "candidate_label": chosen["label"],
                "selection_reason": decision["reason"],
                "reward_margin": decision["reward_margin"],
                "text": sft_text,
            })

    summary = {
        "created_at": utc_now(),
        "eval_samples": str(args.eval_samples),
        "candidates": [
            {"label": label, "rows": len(rows)}
            for label, rows in candidate_sets
        ],
        "pair_output": str(args.pair_output),
        "sft_output": str(args.sft_output),
        "pair_rows": len(pair_rows),
        "sft_rows": len(sft_rows),
        "pair_sources": dict(sorted(pair_sources.items())),
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "thresholds": {
            "min_reward_margin": args.min_reward_margin,
            "min_overlap_margin": args.min_overlap_margin,
            "min_chosen_overlap": args.min_chosen_overlap,
            "max_risk_delta": args.max_risk_delta,
            "long_command_chars": args.long_command_chars,
        },
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


def load_jsonl_by_key(path: Path, *, key_field: str) -> dict[Any, dict[str, Any]]:
    rows: dict[Any, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_index, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = row.get(key_field) or row.get("line_number") or line_index
            rows[key] = row
    return rows


def evaluate_row(row: dict[str, Any], *, label: str, long_command_chars: int) -> dict[str, Any]:
    parsed = parse_planner_json(row.get("generated_text", ""))
    schema = row.get("schema") if isinstance(row.get("schema"), dict) else score_schema(parsed)
    quality = (
        row.get("command_quality")
        if isinstance(row.get("command_quality"), dict)
        else command_quality_features(parsed, schema=schema, long_command_chars=long_command_chars)
    )
    scored = score_candidate(row | {"schema": schema, "command_quality": quality}, parsed)
    metrics = {
        "schema_valid": bool(schema.get("schema_valid", False)),
        "command_overlap": float(row.get("command_overlap") or 0.0),
        "candidate_score": float(scored["score"]),
        "risk_score": risk_score(quality),
        "command_count": int(quality.get("command_count", 0)),
        "max_command_chars": int(quality.get("max_command_chars", 0)),
        "long_command": bool(quality.get("long_command", False)),
        "script_like_command": bool(quality.get("script_like_command", False)),
        "validation_only_command": bool(quality.get("validation_only_command", False)),
        "complete_with_commands": bool(quality.get("complete_with_commands", False)),
        "low_progress_probe_command": bool(quality.get("low_progress_probe_command", False)),
        "simple_action_command": bool(quality.get("simple_action_command", False)),
        "new_tokens": int(row.get("new_tokens") or 0),
    }
    reward = process_reward(metrics)
    return {
        "label": label,
        "row": row,
        "metrics": metrics,
        "reward": reward,
    }


def process_reward(metrics: dict[str, Any]) -> dict[str, float]:
    schema = 35.0 if metrics["schema_valid"] else -80.0
    relevance = 120.0 * metrics["command_overlap"]
    progress = 0.0
    if metrics["command_count"] == 0:
        progress -= 4.0
    elif metrics["command_count"] <= 2:
        progress += 6.0
    else:
        progress -= min(12.0, 2.0 * (metrics["command_count"] - 2))
    if metrics["simple_action_command"]:
        progress += 3.0
    safety = 0.0
    safety -= 18.0 if metrics["long_command"] else 0.0
    safety -= 24.0 if metrics["script_like_command"] else 0.0
    safety -= 12.0 if metrics["validation_only_command"] else 0.0
    safety -= 8.0 if metrics["complete_with_commands"] else 0.0
    safety -= 18.0 if metrics["low_progress_probe_command"] else 0.0
    efficiency = -min(8.0, metrics["new_tokens"] / 80.0)
    total = schema + relevance + progress + safety + efficiency
    return {
        "schema": round(schema, 4),
        "relevance": round(relevance, 4),
        "progress": round(progress, 4),
        "safety": round(safety, 4),
        "efficiency": round(efficiency, 4),
        "total": round(total, 4),
    }


def should_keep_pair(chosen: dict[str, Any], rejected: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    chosen_metrics = chosen["metrics"]
    rejected_metrics = rejected["metrics"]
    reward_margin = round(chosen["reward"]["total"] - rejected["reward"]["total"], 4)
    overlap_delta = round(chosen_metrics["command_overlap"] - rejected_metrics["command_overlap"], 4)
    risk_delta = round(chosen_metrics["risk_score"] - rejected_metrics["risk_score"], 4)
    if not chosen_metrics["schema_valid"]:
        return keep_result(False, "chosen_schema_invalid", reward_margin, overlap_delta, risk_delta)
    if chosen_metrics["command_overlap"] < args.min_chosen_overlap:
        return keep_result(False, "chosen_overlap_low", reward_margin, overlap_delta, risk_delta)
    if reward_margin < args.min_reward_margin:
        return keep_result(False, "reward_margin_low", reward_margin, overlap_delta, risk_delta)
    if overlap_delta < args.min_overlap_margin:
        return keep_result(False, "overlap_margin_low", reward_margin, overlap_delta, risk_delta)
    if risk_delta > args.max_risk_delta:
        return keep_result(False, "risk_regression", reward_margin, overlap_delta, risk_delta)
    return keep_result(True, "prm_margin", reward_margin, overlap_delta, risk_delta)


def keep_result(
    keep: bool,
    reason: str,
    reward_margin: float,
    overlap_delta: float,
    risk_delta: float,
) -> dict[str, Any]:
    return {
        "keep": keep,
        "reason": reason,
        "reward_margin": reward_margin,
        "overlap_delta": overlap_delta,
        "risk_delta": risk_delta,
    }


def risk_score(quality: dict[str, Any]) -> int:
    score = sum(int(bool(quality.get(feature, False))) for feature in RISK_FEATURES)
    if int(quality.get("command_count", 0)) > 2:
        score += 1
    return score


def clean_completion(text: str) -> str:
    return text.strip()


if __name__ == "__main__":
    main()
