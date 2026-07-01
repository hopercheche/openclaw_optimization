#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluate_planner_sft import utc_now, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge JSONL files and de-duplicate rows by one or more fields.")
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-fields", default="text")
    parser.add_argument("--summary-output", type=Path, default=None)
    args = parser.parse_args()

    key_fields = [field.strip() for field in args.key_fields.split(",") if field.strip()]
    if not key_fields:
        raise SystemExit("--key-fields must contain at least one field")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    input_counts: dict[str, int] = {}
    duplicate_count = 0
    for input_path in args.input:
        input_counts[str(input_path)] = 0
        with input_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                input_counts[str(input_path)] += 1
                key = tuple(row.get(field) for field in key_fields)
                if key in seen:
                    duplicate_count += 1
                    continue
                seen.add(key)
                rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output, rows)
    summary = {
        "created_at": utc_now(),
        "inputs": input_counts,
        "output": str(args.output),
        "key_fields": key_fields,
        "output_rows": len(rows),
        "duplicates_dropped": duplicate_count,
    }
    summary_path = args.summary_output or args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
