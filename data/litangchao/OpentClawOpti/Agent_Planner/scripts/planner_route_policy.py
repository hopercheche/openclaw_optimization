#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from benchmark_planner_rerank import gate_signal, parse_gate_labels
from evaluate_planner_sft import utc_now, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply an Agent_Planner route policy to baseline generations.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--generation-text", default=None)
    parser.add_argument("--generations", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--summary-output", type=Path, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    if args.generation_text is None and args.generations is None:
        raise SystemExit("Provide either --generation-text or --generations.")
    if args.generation_text is not None and args.generations is not None:
        raise SystemExit("Use either --generation-text or --generations, not both.")

    if args.generation_text is not None:
        decision = route_decision({"generated_text": args.generation_text}, config)
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return

    if args.output is None:
        raise SystemExit("--output is required when --generations is used.")
    rows = load_jsonl(args.generations)
    decided_rows = []
    for row in rows:
        decision = route_decision(row, config)
        output_row = dict(row)
        output_row["route_policy"] = decision
        decided_rows.append(output_row)

    summary = summarize(decided_rows, config=config, generations=args.generations, output=args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output, decided_rows)
    summary_path = args.summary_output or args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    route_policy = config.get("route_policy") or {}
    if route_policy.get("type") != "structural_risk_threshold":
        raise SystemExit(f"Unsupported route policy type: {route_policy.get('type')}")
    return config


def route_decision(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    route_policy = config["route_policy"]
    gate_labels = parse_gate_labels(",".join(route_policy["gate_labels"]))
    require_any_labels = parse_optional_labels(route_policy, "require_any_labels")
    suppress_if_only_labels = parse_optional_labels(route_policy, "suppress_if_only_labels")
    suppress_if_any_labels = parse_optional_labels(route_policy, "suppress_if_any_labels")
    long_command_chars = int(route_policy.get("long_command_chars", 120))
    min_extra_risk_score = float(route_policy["min_extra_risk_score"])
    risky, risk_score, active_labels = gate_signal(
        dict(row),
        gate_labels=gate_labels,
        long_command_chars=long_command_chars,
    )
    request_secondary = bool(risky and risk_score >= min_extra_risk_score)
    if request_secondary:
        active_label_set = set(active_labels)
        if require_any_labels and not active_label_set.intersection(require_any_labels):
            request_secondary = False
        if suppress_if_only_labels and active_label_set and active_label_set <= suppress_if_only_labels:
            request_secondary = False
        if suppress_if_any_labels and active_label_set.intersection(suppress_if_any_labels):
            request_secondary = False
    return {
        "profile_name": config.get("profile_name"),
        "policy_type": route_policy["type"],
        "request_secondary": request_secondary,
        "primary_label": route_policy.get("baseline_label"),
        "secondary_label": route_policy.get("secondary_label"),
        "risk_score": risk_score,
        "active_labels": active_labels,
        "min_extra_risk_score": min_extra_risk_score,
        "switch_margin": float(route_policy.get("switch_margin", 0.0)),
        "long_command_chars": long_command_chars,
        "require_any_labels": sorted(require_any_labels),
        "suppress_if_only_labels": sorted(suppress_if_only_labels),
        "suppress_if_any_labels": sorted(suppress_if_any_labels),
    }


def parse_optional_labels(route_policy: dict[str, Any], field: str) -> set[str]:
    raw_labels = route_policy.get(field) or []
    if isinstance(raw_labels, str):
        raw = raw_labels
    else:
        raw = ",".join(str(label) for label in raw_labels)
    return parse_gate_labels(raw)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def summarize(
    rows: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    generations: Path | None,
    output: Path,
) -> dict[str, Any]:
    total = len(rows) or 1
    requested = [row for row in rows if row["route_policy"]["request_secondary"]]
    label_counts = Counter(
        label
        for row in requested
        for label in row["route_policy"].get("active_labels", [])
    )
    return {
        "created_at": utc_now(),
        "profile_name": config.get("profile_name"),
        "config": config.get("profile_name"),
        "generations": str(generations) if generations else None,
        "output": str(output),
        "rows": len(rows),
        "request_secondary_rows": len(requested),
        "request_secondary_rate": round(len(requested) / total, 4),
        "requested_label_counts": dict(sorted(label_counts.items())),
        "min_extra_risk_score": config["route_policy"]["min_extra_risk_score"],
    }


if __name__ == "__main__":
    main()
