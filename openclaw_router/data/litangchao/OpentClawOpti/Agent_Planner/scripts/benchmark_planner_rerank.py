#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluate_planner_sft import parse_planner_json, score_schema, utc_now, write_jsonl
from planner_quality import command_quality_features, score_candidate, summarize_quality_metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline verifier-guided rerank pilot for planner generation candidates."
    )
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="Candidate generation file as LABEL=path/to/generations.jsonl. Repeat for multiple candidates.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--key-field", default="line_number")
    parser.add_argument("--baseline-label", default=None)
    parser.add_argument("--rerank-scope", choices=["all", "risk-gated"], default="risk-gated")
    parser.add_argument("--long-command-chars", type=int, default=120)
    parser.add_argument(
        "--switch-margin",
        type=float,
        default=0.0,
        help="Keep the baseline unless a different candidate beats it by this verifier-score margin.",
    )
    parser.add_argument(
        "--gate-labels",
        default="schema_invalid,long_command,multiline_command,script_like_command,risky_command,validation_only_command,complete_with_commands,incomplete_without_commands,many_commands,low_progress_probe_command",
        help="Comma-separated baseline-risk labels that trigger extra candidates in risk-gated mode.",
    )
    parser.add_argument(
        "--require-any-labels",
        default=None,
        help="Optional comma-separated labels. Extra candidates are considered only when at least one is active.",
    )
    parser.add_argument(
        "--suppress-if-only-labels",
        default=None,
        help="Optional comma-separated labels. Suppress extra candidates when all active labels are in this set.",
    )
    parser.add_argument(
        "--suppress-if-any-labels",
        default=None,
        help="Optional comma-separated labels. Suppress extra candidates whenever any of these labels is active.",
    )
    parser.add_argument(
        "--reject-candidate-labels",
        default=None,
        help="Optional comma-separated command-quality labels. Non-baseline candidates with these labels cannot replace the baseline.",
    )
    parser.add_argument(
        "--max-extra-rate",
        type=float,
        default=None,
        help="Optional budget for risk-gated extra candidates, e.g. 0.09 keeps the highest-risk 9% of groups.",
    )
    parser.add_argument(
        "--min-extra-risk-score",
        type=float,
        default=None,
        help="Optional online-style threshold: only baseline rows with gate score >= this value get extra candidates.",
    )
    parser.add_argument("--max-groups", type=int, default=None)
    args = parser.parse_args()
    if args.max_extra_rate is not None and args.min_extra_risk_score is not None:
        raise SystemExit("Use either --max-extra-rate or --min-extra-risk-score, not both.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidate_specs = [parse_candidate_spec(spec) for spec in args.candidate]
    baseline_label = args.baseline_label or candidate_specs[0][0]
    gate_labels = parse_gate_labels(args.gate_labels)
    require_any_labels = parse_gate_labels(args.require_any_labels or "")
    suppress_if_only_labels = parse_gate_labels(args.suppress_if_only_labels or "")
    suppress_if_any_labels = parse_gate_labels(args.suppress_if_any_labels or "")
    reject_candidate_labels = parse_gate_labels(args.reject_candidate_labels or "")
    grouped = load_grouped_candidates(candidate_specs, key_field=args.key_field)
    group_keys = sorted(grouped)
    if args.max_groups is not None:
        group_keys = group_keys[: args.max_groups]
    allowed_extra_keys = make_allowed_extra_keys(
        grouped,
        group_keys,
        baseline_label=baseline_label,
        gate_labels=gate_labels,
        max_extra_rate=args.max_extra_rate,
        min_extra_risk_score=args.min_extra_risk_score,
        long_command_chars=args.long_command_chars,
        require_any_labels=require_any_labels,
        suppress_if_only_labels=suppress_if_only_labels,
        suppress_if_any_labels=suppress_if_any_labels,
    )

    selected_rows: list[dict[str, Any]] = []
    candidate_score_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    per_label_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for key in group_keys:
        candidates = grouped[key]
        for candidate in candidates:
            per_label_rows[candidate["candidate_label"]].append(candidate)
        baseline = first_label(candidates, baseline_label)
        if baseline is None:
            continue
        baseline_rows.append(baseline)

        scored = []
        for candidate in candidates:
            parsed = parse_planner_json(candidate.get("generated_text", ""))
            if "schema" not in candidate or not isinstance(candidate["schema"], dict):
                candidate["schema"] = score_schema(parsed)
            candidate["command_quality"] = command_quality_features(
                parsed,
                schema=candidate["schema"],
                long_command_chars=args.long_command_chars,
            )
            score = score_candidate(candidate, parsed, long_command_chars=args.long_command_chars)
            scored.append((candidate, score))
            candidate_score_rows.append({
                "key": key,
                "candidate_label": candidate["candidate_label"],
                "candidate_score": score["score"],
                "score_reasons": score["reasons"],
                "schema": candidate["schema"],
                "command_quality": score["features"],
                "command_overlap": candidate.get("command_overlap"),
                "amortized_request_seconds": candidate.get("amortized_request_seconds"),
                "generated_preview": candidate.get("generated_text", "")[:500],
            })

        baseline_risky, baseline_gate_score, baseline_gate_labels = gate_signal(
            baseline,
            gate_labels=gate_labels,
            long_command_chars=args.long_command_chars,
        )
        baseline_risky = baseline_risky and label_filters_pass(
            baseline_gate_labels,
            require_any_labels=require_any_labels,
            suppress_if_only_labels=suppress_if_only_labels,
            suppress_if_any_labels=suppress_if_any_labels,
        )
        if allowed_extra_keys is not None:
            baseline_risky = baseline_risky and key in allowed_extra_keys
        baseline_score = next(score for candidate, score in scored if candidate is baseline)
        if args.rerank_scope == "risk-gated" and not baseline_risky:
            selected = baseline
            selected_score = baseline_score
            considered_extra = False
        else:
            selectable_scored = [
                (candidate, score)
                for candidate, score in scored
                if (
                    candidate["candidate_label"] == baseline_label
                    or not active_reject_labels(score["features"], reject_candidate_labels)
                )
            ]
            best_candidate, best_score = max(
                selectable_scored,
                key=lambda item: (
                    item[1]["score"],
                    int(item[0]["candidate_label"] == baseline_label),
                    -float(item[0].get("new_tokens") or 0),
                ),
            )
            if (
                best_candidate["candidate_label"] != baseline_label
                and best_score["score"] - baseline_score["score"] < args.switch_margin
            ):
                selected = baseline
                selected_score = baseline_score
            else:
                selected = best_candidate
                selected_score = best_score
            considered_extra = True

        selected_copy = dict(selected)
        selected_copy["rerank_key"] = key
        selected_copy["selected_candidate_label"] = selected["candidate_label"]
        selected_copy["selected_candidate_score"] = selected_score["score"]
        selected_copy["selected_score_reasons"] = selected_score["reasons"]
        selected_copy["rerank_scope"] = args.rerank_scope
        selected_copy["rerank_considered_extra"] = considered_extra
        selected_copy["rerank_baseline_risky"] = baseline_risky
        selected_copy["rerank_baseline_gate_score"] = baseline_gate_score
        selected_copy["rerank_baseline_gate_labels"] = baseline_gate_labels
        selected_copy["rerank_require_any_labels"] = sorted(require_any_labels)
        selected_copy["rerank_suppress_if_only_labels"] = sorted(suppress_if_only_labels)
        selected_copy["rerank_suppress_if_any_labels"] = sorted(suppress_if_any_labels)
        selected_copy["rerank_reject_candidate_labels"] = sorted(reject_candidate_labels)
        selected_copy["baseline_candidate_label"] = baseline_label
        selected_copy["baseline_command_overlap"] = baseline.get("command_overlap")
        selected_copy["baseline_amortized_request_seconds"] = baseline.get("amortized_request_seconds")
        selected_rows.append(selected_copy)

    metrics = summarize_rerank(
        selected_rows,
        baseline_rows,
        per_label_rows,
        candidate_score_rows,
        candidate_specs,
        baseline_label=baseline_label,
        rerank_scope=args.rerank_scope,
        long_command_chars=args.long_command_chars,
        switch_margin=args.switch_margin,
        gate_labels=gate_labels,
        max_extra_rate=args.max_extra_rate,
        min_extra_risk_score=args.min_extra_risk_score,
        require_any_labels=require_any_labels,
        suppress_if_only_labels=suppress_if_only_labels,
        suppress_if_any_labels=suppress_if_any_labels,
        reject_candidate_labels=reject_candidate_labels,
    )
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "reranked_generations.jsonl", selected_rows)
    write_jsonl(args.output_dir / "candidate_scores.jsonl", candidate_score_rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def parse_candidate_spec(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise SystemExit(f"Candidate spec must be LABEL=path, got: {spec}")
    label, raw_path = spec.split("=", 1)
    label = label.strip()
    if not label:
        raise SystemExit(f"Candidate label is empty in spec: {spec}")
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise SystemExit(f"Candidate path does not exist: {path}")
    return label, path


def parse_gate_labels(raw_labels: str) -> set[str]:
    labels = {
        label.strip()
        for label in raw_labels.split(",")
        if label.strip()
    }
    allowed = {
        "schema_invalid",
        "long_command",
        "multiline_command",
        "script_like_command",
        "risky_command",
        "validation_only_command",
        "complete_with_commands",
        "incomplete_without_commands",
        "many_commands",
        "low_progress_probe_command",
    }
    unknown = labels - allowed
    if unknown:
        raise SystemExit(f"Unknown gate labels: {sorted(unknown)}")
    return labels


def load_grouped_candidates(
    candidate_specs: list[tuple[str, Path]],
    *,
    key_field: str,
) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for candidate_order, (label, path) in enumerate(candidate_specs):
        with path.open("r", encoding="utf-8") as handle:
            for row_index, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                key = row.get(key_field)
                if key is None:
                    key = row.get("line_number")
                if key is None:
                    key = row_index
                candidate = dict(row)
                candidate["candidate_label"] = label
                candidate["candidate_path"] = str(path)
                candidate["candidate_order"] = candidate_order
                grouped[key].append(candidate)
    return grouped


def first_label(candidates: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("candidate_label") == label:
            return candidate
    return None


def make_allowed_extra_keys(
    grouped: dict[Any, list[dict[str, Any]]],
    group_keys: list[Any],
    *,
    baseline_label: str,
    gate_labels: set[str],
    max_extra_rate: float | None,
    min_extra_risk_score: float | None,
    long_command_chars: int,
    require_any_labels: set[str],
    suppress_if_only_labels: set[str],
    suppress_if_any_labels: set[str],
) -> set[Any] | None:
    if max_extra_rate is None and min_extra_risk_score is None:
        return None
    if min_extra_risk_score is not None:
        allowed = set()
        for key in group_keys:
            baseline = first_label(grouped[key], baseline_label)
            if baseline is None:
                continue
            risky, risk_score, active_labels = gate_signal(
                baseline,
                gate_labels=gate_labels,
                long_command_chars=long_command_chars,
            )
            if (
                risky
                and risk_score >= min_extra_risk_score
                and label_filters_pass(
                    active_labels,
                    require_any_labels=require_any_labels,
                    suppress_if_only_labels=suppress_if_only_labels,
                    suppress_if_any_labels=suppress_if_any_labels,
                )
            ):
                allowed.add(key)
        return allowed
    if not 0.0 <= max_extra_rate <= 1.0:
        raise SystemExit("--max-extra-rate must be between 0 and 1")
    max_extra_count = int(len(group_keys) * max_extra_rate)
    if max_extra_count <= 0:
        return set()
    signals: list[tuple[float, int, Any]] = []
    for order, key in enumerate(group_keys):
        baseline = first_label(grouped[key], baseline_label)
        if baseline is None:
            continue
        risky, risk_score, active_labels = gate_signal(
            baseline,
            gate_labels=gate_labels,
            long_command_chars=long_command_chars,
        )
        if risky and label_filters_pass(
            active_labels,
            require_any_labels=require_any_labels,
            suppress_if_only_labels=suppress_if_only_labels,
            suppress_if_any_labels=suppress_if_any_labels,
        ):
            signals.append((risk_score, -order, key))
    signals.sort(reverse=True)
    return {key for _, _, key in signals[:max_extra_count]}


def gate_signal(
    row: dict[str, Any],
    *,
    gate_labels: set[str],
    long_command_chars: int,
) -> tuple[bool, float, list[str]]:
    parsed = parse_planner_json(row.get("generated_text", ""))
    if "schema" not in row or not isinstance(row["schema"], dict):
        row["schema"] = score_schema(parsed)
    row["command_quality"] = command_quality_features(
        parsed,
        schema=row["schema"],
        long_command_chars=long_command_chars,
    )
    schema = row.get("schema") or {}
    quality = row.get("command_quality") or {}
    checks = {
        "schema_invalid": not schema.get("schema_valid", False),
        "long_command": quality.get("long_command", False),
        "multiline_command": quality.get("multiline_command", False),
        "script_like_command": quality.get("script_like_command", False),
        "risky_command": quality.get("risky_command", False),
        "validation_only_command": quality.get("validation_only_command", False),
        "complete_with_commands": quality.get("complete_with_commands", False),
        "incomplete_without_commands": quality.get("incomplete_without_commands", False),
        "many_commands": int(quality.get("command_count", 0)) > 2,
        "low_progress_probe_command": quality.get("low_progress_probe_command", False),
    }
    weights = {
        "schema_invalid": 100.0,
        "risky_command": 80.0,
        "long_command": 45.0,
        "multiline_command": 40.0,
        "script_like_command": 35.0,
        "many_commands": 20.0,
        "validation_only_command": 16.0,
        "complete_with_commands": 12.0,
        "incomplete_without_commands": 12.0,
        "low_progress_probe_command": 30.0,
    }
    active_labels = [label for label in sorted(gate_labels) if checks[label]]
    risk_score = sum(weights[label] for label in active_labels)
    if quality.get("max_command_chars", 0):
        risk_score += min(10.0, float(quality["max_command_chars"]) / 24.0)
    return bool(active_labels), round(risk_score, 4), active_labels


def label_filters_pass(
    active_labels: list[str],
    *,
    require_any_labels: set[str],
    suppress_if_only_labels: set[str],
    suppress_if_any_labels: set[str],
) -> bool:
    active_label_set = set(active_labels)
    if require_any_labels and not active_label_set.intersection(require_any_labels):
        return False
    if suppress_if_only_labels and active_label_set and active_label_set <= suppress_if_only_labels:
        return False
    if suppress_if_any_labels and active_label_set.intersection(suppress_if_any_labels):
        return False
    return True


def active_reject_labels(features: dict[str, Any], reject_labels: set[str]) -> list[str]:
    return sorted(label for label in reject_labels if features.get(label))


def summarize_rerank(
    selected_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    per_label_rows: dict[str, list[dict[str, Any]]],
    candidate_score_rows: list[dict[str, Any]],
    candidate_specs: list[tuple[str, Path]],
    *,
    baseline_label: str,
    rerank_scope: str,
    long_command_chars: int,
    switch_margin: float,
    gate_labels: set[str],
    max_extra_rate: float | None,
    min_extra_risk_score: float | None,
    require_any_labels: set[str],
    suppress_if_only_labels: set[str],
    suppress_if_any_labels: set[str],
    reject_candidate_labels: set[str],
) -> dict[str, Any]:
    total = len(selected_rows) or 1
    label_counts = Counter(row["selected_candidate_label"] for row in selected_rows)
    changed_rows = [
        row for row in selected_rows
        if row["selected_candidate_label"] != row["baseline_candidate_label"]
    ]
    overlap_deltas = [
        float(row.get("command_overlap") or 0.0) - float(row.get("baseline_command_overlap") or 0.0)
        for row in selected_rows
    ]
    improved = sum(1 for delta in overlap_deltas if delta > 0)
    worsened = sum(1 for delta in overlap_deltas if delta < 0)
    considered_extra = sum(1 for row in selected_rows if row.get("rerank_considered_extra"))
    return {
        "created_at": utc_now(),
        "candidate_specs": [
            {"label": label, "path": str(path)}
            for label, path in candidate_specs
        ],
        "baseline_label": baseline_label,
        "rerank_scope": rerank_scope,
        "long_command_chars": long_command_chars,
        "switch_margin": switch_margin,
        "gate_labels": sorted(gate_labels),
        "require_any_labels": sorted(require_any_labels),
        "suppress_if_only_labels": sorted(suppress_if_only_labels),
        "suppress_if_any_labels": sorted(suppress_if_any_labels),
        "reject_candidate_labels": sorted(reject_candidate_labels),
        "max_extra_rate": max_extra_rate,
        "min_extra_risk_score": min_extra_risk_score,
        "groups": len(selected_rows),
        "considered_extra_rate": round(considered_extra / total, 4),
        "changed_from_baseline_rate": round(len(changed_rows) / total, 4),
        "selected_label_counts": dict(sorted(label_counts.items())),
        "baseline": summarize_rows(baseline_rows, long_command_chars=long_command_chars),
        "selected": summarize_rows(selected_rows, long_command_chars=long_command_chars),
        "candidate_labels": {
            label: summarize_rows(rows, long_command_chars=long_command_chars)
            for label, rows in sorted(per_label_rows.items())
        },
        "overlap_delta_mean": round(statistics.mean(overlap_deltas) if overlap_deltas else 0.0, 4),
        "overlap_improved_rate": round(improved / total, 4),
        "overlap_worsened_rate": round(worsened / total, 4),
        "estimated_full_candidate_mean_seconds": estimate_full_candidate_seconds(candidate_score_rows),
        "estimated_online_mean_seconds": estimate_online_seconds(
            selected_rows,
            candidate_score_rows,
            baseline_label=baseline_label,
        ),
        "estimated_selected_row_mean_seconds": mean_seconds(selected_rows),
        "estimated_baseline_mean_seconds": mean_seconds(baseline_rows),
        "worst_selected_examples": worst_examples(selected_rows),
    }


def summarize_rows(rows: list[dict[str, Any]], *, long_command_chars: int) -> dict[str, Any]:
    total = len(rows) or 1
    overlaps = [float(row.get("command_overlap") or 0.0) for row in rows]
    quality = summarize_quality_metrics(rows, long_command_chars=long_command_chars)
    return {
        "generation_examples": len(rows),
        "schema_valid_rate": round(
            sum(1 for row in rows if (row.get("schema") or {}).get("schema_valid")) / total,
            4,
        ),
        "command_overlap_mean": round(statistics.mean(overlaps) if overlaps else 0.0, 4),
        "long_command_rate": quality["long_command_rate"],
        "script_like_command_rate": quality["script_like_command_rate"],
        "validation_only_command_rate": quality["validation_only_command_rate"],
        "mean_max_command_chars": quality["mean_max_command_chars"],
        "mean_amortized_request_seconds": mean_seconds(rows),
    }


def estimate_full_candidate_seconds(candidate_score_rows: list[dict[str, Any]]) -> float:
    by_key: dict[Any, list[float]] = defaultdict(list)
    for row in candidate_score_rows:
        seconds = row.get("amortized_request_seconds")
        if seconds is None:
            continue
        by_key[row["key"]].append(float(seconds))
    if not by_key:
        return 0.0
    return round(statistics.mean(sum(values) for values in by_key.values()), 6)


def estimate_online_seconds(
    selected_rows: list[dict[str, Any]],
    candidate_score_rows: list[dict[str, Any]],
    *,
    baseline_label: str,
) -> float:
    by_key: dict[Any, dict[str, float]] = defaultdict(dict)
    for row in candidate_score_rows:
        seconds = row.get("amortized_request_seconds")
        if seconds is None:
            continue
        by_key[row["key"]][row["candidate_label"]] = float(seconds)
    estimates: list[float] = []
    for row in selected_rows:
        key = row.get("rerank_key")
        baseline_seconds = float(row.get("baseline_amortized_request_seconds") or 0.0)
        if not row.get("rerank_considered_extra"):
            estimates.append(baseline_seconds)
            continue
        extra_seconds = sum(
            seconds
            for label, seconds in by_key.get(key, {}).items()
            if label != baseline_label
        )
        estimates.append(baseline_seconds + extra_seconds)
    return round(statistics.mean(estimates) if estimates else 0.0, 6)


def mean_seconds(rows: list[dict[str, Any]]) -> float:
    seconds = [
        float(row.get("amortized_request_seconds"))
        for row in rows
        if row.get("amortized_request_seconds") is not None
    ]
    return round(statistics.mean(seconds) if seconds else 0.0, 6)


def worst_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "line_number": row.get("line_number"),
            "selected_candidate_label": row.get("selected_candidate_label"),
            "baseline_candidate_label": row.get("baseline_candidate_label"),
            "command_overlap": row.get("command_overlap"),
            "baseline_command_overlap": row.get("baseline_command_overlap"),
            "selected_candidate_score": row.get("selected_candidate_score"),
            "selected_score_reasons": row.get("selected_score_reasons"),
            "baseline_gate_score": row.get("rerank_baseline_gate_score"),
            "baseline_gate_labels": row.get("rerank_baseline_gate_labels"),
            "generated_preview": row.get("generated_text", "")[:500],
        }
        for row in sorted(
            rows,
            key=lambda item: (
                float(item.get("command_overlap") or 0.0),
                -float(item.get("selected_candidate_score") or 0.0),
            ),
        )[:10]
    ]


def render_report(metrics: dict[str, Any]) -> str:
    baseline = metrics["baseline"]
    selected = metrics["selected"]
    lines = [
        "# Agent Planner Verifier Rerank Pilot",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Baseline label: `{metrics['baseline_label']}`",
        f"- Rerank scope: `{metrics['rerank_scope']}`",
        f"- Switch margin: {metrics['switch_margin']}",
        f"- Gate labels: `{metrics['gate_labels']}`",
        f"- Max extra rate: {metrics['max_extra_rate']}",
        f"- Min extra risk score: {metrics['min_extra_risk_score']}",
        f"- Groups: {metrics['groups']}",
        f"- Considered extra rate: {metrics['considered_extra_rate']:.2%}",
        f"- Changed from baseline rate: {metrics['changed_from_baseline_rate']:.2%}",
        "",
        "## Summary",
        "",
        "| Route | Schema | Overlap | Long cmd | Script-like | Validation-only | Mean seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| baseline | {baseline['schema_valid_rate']:.2%} | {baseline['command_overlap_mean']:.4f} | "
        f"{baseline['long_command_rate']:.2%} | {baseline['script_like_command_rate']:.2%} | "
        f"{baseline['validation_only_command_rate']:.2%} | {baseline['mean_amortized_request_seconds']:.4f}s |",
        f"| selected | {selected['schema_valid_rate']:.2%} | {selected['command_overlap_mean']:.4f} | "
        f"{selected['long_command_rate']:.2%} | {selected['script_like_command_rate']:.2%} | "
        f"{selected['validation_only_command_rate']:.2%} | {selected['mean_amortized_request_seconds']:.4f}s |",
        "",
        "## Rerank Effect",
        "",
        f"- Selected label counts: `{metrics['selected_label_counts']}`",
        f"- Mean overlap delta: {metrics['overlap_delta_mean']:.4f}",
        f"- Overlap improved rate: {metrics['overlap_improved_rate']:.2%}",
        f"- Overlap worsened rate: {metrics['overlap_worsened_rate']:.2%}",
        f"- Estimated full-candidate mean seconds: {metrics['estimated_full_candidate_mean_seconds']:.4f}s",
        f"- Estimated online mean seconds: {metrics['estimated_online_mean_seconds']:.4f}s",
    ]
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
