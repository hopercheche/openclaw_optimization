#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer

from evaluate_planner_sft import utc_now


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline draft/target agreement benchmark for DeepSpec-style speculative planner decoding."
    )
    parser.add_argument("--target-generations", type=Path, required=True)
    parser.add_argument("--draft-generations", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--block-sizes", default="2,4,6,8,12")
    parser.add_argument("--max-examples", type=int, default=None)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(
        str(args.tokenizer),
        trust_remote_code=True,
        local_files_only=True,
    )
    block_sizes = parse_block_sizes(args.block_sizes)
    target_rows = load_rows(args.target_generations, max_examples=args.max_examples)
    draft_rows = load_rows(args.draft_generations, max_examples=args.max_examples)
    pairs = pair_rows(target_rows, draft_rows)
    if not pairs:
        raise SystemExit("No matching original_index rows found between target and draft generations.")

    rows = [
        score_pair(
            target,
            draft,
            tokenizer=tokenizer,
            block_sizes=block_sizes,
        )
        for target, draft in pairs
    ]
    metrics = {
        "created_at": utc_now(),
        "run_config": {
            "target_generations": str(args.target_generations),
            "draft_generations": str(args.draft_generations),
            "tokenizer": str(args.tokenizer),
            "output_dir": str(args.output_dir),
            "block_sizes": block_sizes,
            "max_examples": args.max_examples,
            "matched_examples": len(rows),
        },
        "summary": summarize(rows, block_sizes),
    }
    write_jsonl(args.output_dir / "acceptance_rows.jsonl", rows)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def parse_block_sizes(value: str) -> list[int]:
    sizes = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        size = int(item)
        if size < 1:
            raise SystemExit("--block-sizes must contain positive integers")
        sizes.append(size)
    if not sizes:
        raise SystemExit("--block-sizes cannot be empty")
    return sizes


def load_rows(path: Path, *, max_examples: int | None) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if max_examples is not None and len(rows) >= max_examples:
                break
    return rows


def pair_rows(
    target_rows: list[dict[str, Any]],
    draft_rows: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    draft_by_index = {int(row["original_index"]): row for row in draft_rows}
    pairs = []
    for target in target_rows:
        draft = draft_by_index.get(int(target["original_index"]))
        if draft is not None:
            pairs.append((target, draft))
    pairs.sort(key=lambda pair: int(pair[0]["original_index"]))
    return pairs


def score_pair(
    target: dict[str, Any],
    draft: dict[str, Any],
    *,
    tokenizer,
    block_sizes: list[int],
) -> dict[str, Any]:
    target_ids = tokenizer.encode(str(target.get("generated_text", "")), add_special_tokens=False)
    draft_ids = tokenizer.encode(str(draft.get("generated_text", "")), add_special_tokens=False)
    prefix = common_prefix_len(target_ids, draft_ids)
    aligned_matches = sum(
        1
        for target_id, draft_id in zip(target_ids, draft_ids)
        if target_id == draft_id
    )
    min_len = min(len(target_ids), len(draft_ids))
    block_scores = {
        str(block_size): score_blocks(target_ids, draft_ids, block_size)
        for block_size in block_sizes
    }
    target_quality = target.get("command_quality") or {}
    draft_quality = draft.get("command_quality") or {}
    return {
        "original_index": int(target["original_index"]),
        "line_number": target.get("line_number"),
        "target_new_tokens": int(target.get("new_tokens") or len(target_ids)),
        "draft_new_tokens": int(draft.get("new_tokens") or len(draft_ids)),
        "target_tokenized_tokens": len(target_ids),
        "draft_tokenized_tokens": len(draft_ids),
        "common_prefix_tokens": prefix,
        "common_prefix_rate_target": round(prefix / max(len(target_ids), 1), 4),
        "aligned_token_match_count": aligned_matches,
        "aligned_token_match_rate": round(aligned_matches / max(min_len, 1), 4),
        "exact_text_match": target.get("generated_text") == draft.get("generated_text"),
        "target_schema_valid": bool((target.get("schema") or {}).get("schema_valid")),
        "draft_schema_valid": bool((draft.get("schema") or {}).get("schema_valid")),
        "target_command_overlap": float(target.get("command_overlap") or 0.0),
        "draft_command_overlap": float(draft.get("command_overlap") or 0.0),
        "target_long_command": bool(target_quality.get("long_command")),
        "draft_long_command": bool(draft_quality.get("long_command")),
        "target_script_like_command": bool(target_quality.get("script_like_command")),
        "draft_script_like_command": bool(draft_quality.get("script_like_command")),
        "target_generated_text": target.get("generated_text", ""),
        "draft_generated_text": draft.get("generated_text", ""),
        "block_scores": block_scores,
    }


def common_prefix_len(left: list[int], right: list[int]) -> int:
    count = 0
    for left_id, right_id in zip(left, right):
        if left_id != right_id:
            break
        count += 1
    return count


def score_blocks(target_ids: list[int], draft_ids: list[int], block_size: int) -> dict[str, Any]:
    accepted_prefixes = []
    full_accepts = 0
    block_count = 0
    for start in range(0, len(target_ids), block_size):
        target_block = target_ids[start:start + block_size]
        draft_block = draft_ids[start:start + block_size]
        if not target_block:
            continue
        block_count += 1
        accepted = common_prefix_len(target_block, draft_block)
        accepted_prefixes.append(accepted)
        if accepted == len(target_block) and len(draft_block) >= len(target_block):
            full_accepts += 1
    accepted_total = sum(accepted_prefixes)
    advanced_per_verify = [min(value, block_size) + 1 for value in accepted_prefixes]
    return {
        "block_size": block_size,
        "block_count": block_count,
        "full_accept_block_rate": round(full_accepts / max(block_count, 1), 4),
        "mean_accepted_prefix_tokens": round(statistics.mean(accepted_prefixes) if accepted_prefixes else 0.0, 4),
        "accepted_prefix_token_rate": round(accepted_total / max(len(target_ids), 1), 4),
        "target_step_reduction_upper_bound": round(
            statistics.mean(advanced_per_verify) if advanced_per_verify else 1.0,
            4,
        ),
    }


def summarize(rows: list[dict[str, Any]], block_sizes: list[int]) -> dict[str, Any]:
    total = len(rows) or 1
    summary: dict[str, Any] = {
        "matched_examples": len(rows),
        "target_schema_valid_rate": round(sum(row["target_schema_valid"] for row in rows) / total, 4),
        "draft_schema_valid_rate": round(sum(row["draft_schema_valid"] for row in rows) / total, 4),
        "target_command_overlap_mean": mean(row["target_command_overlap"] for row in rows),
        "draft_command_overlap_mean": mean(row["draft_command_overlap"] for row in rows),
        "exact_text_match_rate": round(sum(row["exact_text_match"] for row in rows) / total, 4),
        "mean_common_prefix_tokens": mean(row["common_prefix_tokens"] for row in rows),
        "mean_common_prefix_rate_target": mean(row["common_prefix_rate_target"] for row in rows),
        "mean_aligned_token_match_rate": mean(row["aligned_token_match_rate"] for row in rows),
        "p50_common_prefix_tokens": percentile([row["common_prefix_tokens"] for row in rows], 0.50),
        "p90_common_prefix_tokens": percentile([row["common_prefix_tokens"] for row in rows], 0.90),
        "p95_common_prefix_tokens": percentile([row["common_prefix_tokens"] for row in rows], 0.95),
        "risk_slice_counts": dict(sorted(Counter(risk_slice(row) for row in rows).items())),
        "by_block_size": {},
        "by_risk_slice": {},
    }
    for block_size in block_sizes:
        key = str(block_size)
        block_rows = [row["block_scores"][key] for row in rows]
        summary["by_block_size"][key] = {
            "full_accept_block_rate": mean(row["full_accept_block_rate"] for row in block_rows),
            "mean_accepted_prefix_tokens": mean(row["mean_accepted_prefix_tokens"] for row in block_rows),
            "accepted_prefix_token_rate": mean(row["accepted_prefix_token_rate"] for row in block_rows),
            "target_step_reduction_upper_bound": mean(row["target_step_reduction_upper_bound"] for row in block_rows),
        }
    for label in sorted(set(risk_slice(row) for row in rows)):
        slice_rows = [row for row in rows if risk_slice(row) == label]
        if not slice_rows:
            continue
        summary["by_risk_slice"][label] = {
            "count": len(slice_rows),
            "mean_common_prefix_tokens": mean(row["common_prefix_tokens"] for row in slice_rows),
            "mean_common_prefix_rate_target": mean(row["common_prefix_rate_target"] for row in slice_rows),
            "mean_aligned_token_match_rate": mean(row["aligned_token_match_rate"] for row in slice_rows),
        }
    return summary


def risk_slice(row: dict[str, Any]) -> str:
    if row["target_script_like_command"] or row["draft_script_like_command"]:
        return "script_like"
    if row["target_long_command"] or row["draft_long_command"]:
        return "long_command"
    return "normal"


def mean(values) -> float:
    items = list(values)
    return round(statistics.mean(items) if items else 0.0, 4)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return round(float(ordered[index]), 4)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def render_report(metrics: dict[str, Any]) -> str:
    summary = metrics["summary"]
    lines = [
        "# Stage11 DeepSpec-Style Draft Acceptance Benchmark",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Target generations: `{metrics['run_config']['target_generations']}`",
        f"- Draft generations: `{metrics['run_config']['draft_generations']}`",
        f"- Matched examples: {summary['matched_examples']}",
        "",
        "## Overall",
        "",
        f"- Target schema valid: {summary['target_schema_valid_rate']:.2%}",
        f"- Draft schema valid: {summary['draft_schema_valid_rate']:.2%}",
        f"- Target overlap: {summary['target_command_overlap_mean']:.4f}",
        f"- Draft overlap: {summary['draft_command_overlap_mean']:.4f}",
        f"- Exact text match: {summary['exact_text_match_rate']:.2%}",
        f"- Mean common prefix: {summary['mean_common_prefix_tokens']:.2f} tokens "
        f"({summary['mean_common_prefix_rate_target']:.2%} of target)",
        f"- Mean aligned token match: {summary['mean_aligned_token_match_rate']:.2%}",
        "",
        "## Block Proxy",
        "",
        "| Block | Full-accept blocks | Accepted-prefix token rate | Mean accepted prefix | Target-step reduction upper bound |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for block_size, row in summary["by_block_size"].items():
        lines.append(
            f"| {block_size} | {row['full_accept_block_rate']:.2%} | "
            f"{row['accepted_prefix_token_rate']:.2%} | {row['mean_accepted_prefix_tokens']:.2f} | "
            f"{row['target_step_reduction_upper_bound']:.2f}x |"
        )
    lines.extend([
        "",
        "## Risk Slices",
        "",
        "| Slice | Count | Prefix tokens | Prefix rate | Aligned token match |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for label, row in summary["by_risk_slice"].items():
        lines.append(
            f"| {label} | {row['count']} | {row['mean_common_prefix_tokens']:.2f} | "
            f"{row['mean_common_prefix_rate_target']:.2%} | {row['mean_aligned_token_match_rate']:.2%} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
