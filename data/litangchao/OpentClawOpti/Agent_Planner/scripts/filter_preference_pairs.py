#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter Agent_Planner preference pairs for lower-noise DPO training.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-overlap-delta", type=float, default=0.1)
    parser.add_argument("--min-score-delta", type=float, default=0.0)
    parser.add_argument("--max-risk-delta", type=float, default=0.0)
    parser.add_argument(
        "--require-selection-reason",
        action="append",
        default=[],
        help="Optional selection_reason allow-list. Can be repeated.",
    )
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    total = 0
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            row = json.loads(line)
            keep, reason = should_keep(row, args)
            if keep:
                rows.append(row)
            else:
                dropped[reason] += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "created_at": utc_now(),
        "input": str(args.input),
        "output": str(args.output),
        "input_rows": total,
        "output_rows": len(rows),
        "min_overlap_delta": args.min_overlap_delta,
        "min_score_delta": args.min_score_delta,
        "max_risk_delta": args.max_risk_delta,
        "require_selection_reason": args.require_selection_reason,
        "dropped": dict(sorted(dropped.items())),
    }
    summary_path = args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def should_keep(row: dict[str, Any], args: argparse.Namespace) -> tuple[bool, str]:
    if args.require_selection_reason and row.get("selection_reason") not in set(args.require_selection_reason):
        return False, "selection_reason"
    if float(row.get("overlap_delta") or 0.0) < args.min_overlap_delta:
        return False, "overlap_delta"
    if float(row.get("score_delta") or 0.0) < args.min_score_delta:
        return False, "score_delta"
    if float(row.get("risk_delta") or 0.0) > args.max_risk_delta:
        return False, "risk_delta"
    for key in ("prompt", "chosen", "rejected"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            return False, f"missing_{key}"
    return True, "kept"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
