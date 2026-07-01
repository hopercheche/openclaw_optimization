#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import statistics
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch

from benchmark_transformers_batch_planner import (
    apply_extra_output_policy,
    load_model,
    make_batches,
    merge_retry_rows,
    run_generation_batches,
    summarize_padding,
    summarize_rows,
)
from evaluate_planner_sft import load_examples, parse_planner_json, score_schema, truncate_prompt, utc_now, write_jsonl
from planner_quality import command_quality_features, score_candidate, summarize_quality_metrics
from planner_route_policy import load_config, route_decision
from transformers import AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark online-style Stage7/Stage9 structural-risk route.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-line", type=int, default=5001)
    parser.add_argument("--generation-examples", type=int, default=1000)
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    generation_config = config["generation"]
    secondary_generation_config = dict(generation_config)
    secondary_generation_config.update(config.get("secondary_generation") or {})
    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this benchmark, but torch cannot see a CUDA device.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    examples = load_examples(args.eval_file, args.start_line, args.generation_examples)
    if not examples:
        raise SystemExit(f"No valid examples found in {args.eval_file} starting at line {args.start_line}")

    run_config = {
        "created_at": utc_now(),
        "profile": str(args.config),
        "profile_name": config.get("profile_name"),
        "eval_file": str(args.eval_file),
        "output_dir": str(args.output_dir),
        "start_line": args.start_line,
        "generation_examples": len(examples),
        "generation": generation_config,
        "secondary_generation": secondary_generation_config,
        "route_policy": config["route_policy"],
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch_version": torch.__version__,
        "torch_cuda": torch.version.cuda,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "eval_samples.jsonl", [asdict(example) for example in examples])

    started = time.perf_counter()
    primary_rows, primary_batch_seconds = generate_model_rows(
        model_path=Path(config["primary_model"]["path"]),
        examples=examples,
        generation_config=generation_config,
        retry_policy=config.get("invalid_retry_policy"),
        candidate_label=config["primary_model"]["label"],
    )
    primary_elapsed = time.perf_counter() - started
    route_rows = []
    requested_indices = []
    for row in primary_rows:
        decision = route_decision(row, config)
        route_rows.append({
            "original_index": row["original_index"],
            "line_number": row.get("line_number"),
            "route_policy": decision,
        })
        if decision["request_secondary"]:
            requested_indices.append(row["original_index"])

    cleanup_cuda()
    secondary_rows: list[dict[str, Any]] = []
    secondary_batch_seconds: list[float] = []
    secondary_elapsed = 0.0
    if requested_indices:
        secondary_started = time.perf_counter()
        requested_examples = [(index, examples[index]) for index in sorted(set(requested_indices))]
        secondary_rows, secondary_batch_seconds = generate_model_rows(
            model_path=Path(config["secondary_model"]["path"]),
            examples=requested_examples,
            generation_config=secondary_generation_config,
            retry_policy=config.get("invalid_retry_policy"),
            candidate_label=config["secondary_model"]["label"],
        )
        secondary_elapsed = time.perf_counter() - secondary_started
        cleanup_cuda()

    selected_rows = select_route_rows(
        primary_rows,
        secondary_rows,
        config=config,
    )
    primary_prompt_lengths = [int(row.get("prompt_tokens") or 0) for row in primary_rows]
    primary_padding_stats = {"padding_tokens": 0, "padding_fraction": 0.0}
    primary_result = summarize_rows(
        primary_rows,
        label="primary_final",
        total_examples=len(examples),
        total_generation_seconds=primary_elapsed,
        batch_seconds=primary_batch_seconds,
        prompt_lengths=primary_prompt_lengths,
        padding_stats=primary_padding_stats,
    )
    selected_result = summarize_selected_rows(
        selected_rows,
        total_examples=len(examples),
        primary_batch_seconds=primary_batch_seconds,
        secondary_batch_seconds=secondary_batch_seconds,
    )
    metrics = {
        "created_at": utc_now(),
        "run_config": run_config,
        "route": {
            "requested_secondary_count": len(set(requested_indices)),
            "requested_secondary_rate": round(len(set(requested_indices)) / max(len(examples), 1), 4),
            "secondary_rows_generated": len(secondary_rows),
            "changed_from_primary_count": sum(1 for row in selected_rows if row["selected_candidate_label"] != config["primary_model"]["label"]),
            "changed_from_primary_rate": round(
                sum(1 for row in selected_rows if row["selected_candidate_label"] != config["primary_model"]["label"]) / max(len(examples), 1),
                4,
            ),
            "secondary_rejected_count": sum(1 for row in selected_rows if row.get("secondary_rejected_labels")),
            "secondary_rejected_label_counts": dict(sorted(Counter(
                label
                for row in selected_rows
                for label in row.get("secondary_rejected_labels", [])
            ).items())),
            "primary_elapsed_seconds": round(primary_elapsed, 6),
            "secondary_elapsed_seconds": round(secondary_elapsed, 6),
        },
        "results": [primary_result, selected_result],
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "primary_generations.jsonl", primary_rows)
    if secondary_rows:
        write_jsonl(args.output_dir / "secondary_generations.jsonl", secondary_rows)
    write_jsonl(args.output_dir / "route_decisions.jsonl", route_rows)
    write_jsonl(args.output_dir / "generations.jsonl", selected_rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def generate_model_rows(
    *,
    model_path: Path,
    examples,
    generation_config: dict[str, Any],
    retry_policy: str | None,
    candidate_label: str,
) -> tuple[list[dict[str, Any]], list[float]]:
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path),
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    model = load_model(
        model_path,
        generation_config.get("dtype", "bf16"),
        generation_config.get("attn_implementation"),
        generation_config.get("device_placement", "cuda"),
    )
    device = next(model.parameters()).device
    indexed_examples = normalize_examples(examples)
    prepared = prepare_indexed_examples(
        indexed_examples,
        tokenizer=tokenizer,
        max_prompt_tokens=max(1, int(generation_config.get("max_seq_length", 1024)) - 8),
        sort_by_prompt_length=bool(generation_config.get("sort_by_prompt_length", True)),
        extra_output_policy=None,
    )
    batches = make_batches(
        prepared,
        batch_size=int(generation_config.get("batch_size", 32)),
        max_batch_prompt_tokens=generation_config.get("max_batch_prompt_tokens"),
    )
    rows, batch_seconds = run_generation_batches(
        model=model,
        tokenizer=tokenizer,
        device=device,
        prepared_batches=batches,
        max_new_tokens=int(generation_config.get("max_new_tokens", 256)),
        pass_name=candidate_label,
    )
    final_rows = rows
    retry_batch_seconds: list[float] = []
    if retry_policy:
        retry_items = build_retry_items_indexed(
            indexed_examples,
            rows,
            tokenizer=tokenizer,
            max_prompt_tokens=max(1, int(generation_config.get("max_seq_length", 1024)) - 8),
            extra_output_policy=retry_policy,
        )
        if retry_items:
            retry_batches = make_batches(
                retry_items,
                batch_size=int(generation_config.get("batch_size", 32)),
                max_batch_prompt_tokens=generation_config.get("max_batch_prompt_tokens"),
            )
            retry_rows, retry_batch_seconds = run_generation_batches(
                model=model,
                tokenizer=tokenizer,
                device=device,
                prepared_batches=retry_batches,
                max_new_tokens=int(generation_config.get("retry_invalid_max_new_tokens") or generation_config.get("max_new_tokens", 256)),
                pass_name=f"{candidate_label}_retry_invalid",
            )
            final_rows = merge_retry_rows(rows, retry_rows)
    for row in final_rows:
        row["candidate_label"] = candidate_label
    del model
    del tokenizer
    return final_rows, batch_seconds + retry_batch_seconds


def normalize_examples(examples) -> list[tuple[int, Any]]:
    if not examples:
        return []
    first = examples[0]
    if isinstance(first, tuple):
        return list(examples)
    return list(enumerate(examples))


def prepare_indexed_examples(
    indexed_examples: list[tuple[int, Any]],
    *,
    tokenizer,
    max_prompt_tokens: int,
    sort_by_prompt_length: bool,
    extra_output_policy: str | None,
) -> list[dict[str, Any]]:
    prepared = [
        {
            "original_index": original_index,
            "example": example,
            "prompt_ids": truncate_prompt(
                tokenizer,
                apply_extra_output_policy(example.prompt, extra_output_policy),
                max_prompt_tokens=max_prompt_tokens,
            ),
        }
        for original_index, example in indexed_examples
    ]
    if sort_by_prompt_length:
        prepared.sort(key=lambda item: len(item["prompt_ids"]))
    return prepared


def build_retry_items_indexed(
    indexed_examples: list[tuple[int, Any]],
    rows: list[dict[str, Any]],
    *,
    tokenizer,
    max_prompt_tokens: int,
    extra_output_policy: str,
) -> list[dict[str, Any]]:
    examples_by_index = dict(indexed_examples)
    retry_items = []
    for row in rows:
        if row["schema"]["schema_valid"]:
            continue
        original_index = row["original_index"]
        example = examples_by_index[original_index]
        retry_items.append({
            "original_index": original_index,
            "example": example,
            "prompt_ids": truncate_prompt(
                tokenizer,
                apply_extra_output_policy(example.prompt, extra_output_policy),
                max_prompt_tokens=max_prompt_tokens,
            ),
        })
    return retry_items


def select_route_rows(
    primary_rows: list[dict[str, Any]],
    secondary_rows: list[dict[str, Any]],
    *,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    secondary_by_index = {row["original_index"]: row for row in secondary_rows}
    reject_secondary_labels = set(config["route_policy"].get("reject_secondary_labels") or [])
    selected_rows = []
    for primary in primary_rows:
        decision = route_decision(primary, config)
        secondary = secondary_by_index.get(primary["original_index"])
        primary_score = candidate_score(primary, config)
        selected = primary
        selected_score = primary_score
        secondary_score = None
        secondary_rejected_labels: list[str] = []
        if decision["request_secondary"] and secondary is not None:
            secondary_score = candidate_score(secondary, config)
            secondary_rejected_labels = active_reject_labels(
                secondary_score["features"],
                reject_secondary_labels,
            )
            if (
                not secondary_rejected_labels
                and secondary_score["score"] - primary_score["score"] >= float(config["route_policy"].get("switch_margin", 0.0))
            ):
                selected = secondary
                selected_score = secondary_score
        selected_copy = dict(selected)
        selected_copy["route_policy"] = decision
        selected_copy["selected_candidate_label"] = selected.get("candidate_label")
        selected_copy["selected_candidate_score"] = selected_score["score"]
        selected_copy["selected_score_reasons"] = selected_score["reasons"]
        selected_copy["primary_candidate_score"] = primary_score["score"]
        selected_copy["secondary_candidate_score"] = secondary_score["score"] if secondary_score else None
        selected_copy["secondary_rejected_labels"] = secondary_rejected_labels
        selected_copy["baseline_command_overlap"] = primary.get("command_overlap")
        selected_rows.append(selected_copy)
    selected_rows.sort(key=lambda row: row["original_index"])
    return selected_rows


def active_reject_labels(features: dict[str, Any], reject_labels: set[str]) -> list[str]:
    return sorted(label for label in reject_labels if features.get(label))


def candidate_score(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_planner_json(row.get("generated_text", ""))
    schema = row.get("schema") if isinstance(row.get("schema"), dict) else score_schema(parsed)
    quality = command_quality_features(
        parsed,
        schema=schema,
        long_command_chars=int(config["route_policy"].get("long_command_chars", 120)),
    )
    return score_candidate(row | {"schema": schema, "command_quality": quality}, parsed)


def summarize_selected_rows(
    rows: list[dict[str, Any]],
    *,
    total_examples: int,
    primary_batch_seconds: list[float],
    secondary_batch_seconds: list[float],
) -> dict[str, Any]:
    total = total_examples or 1
    field_scores = [row["schema"]["required_field_fraction"] for row in rows]
    command_overlaps = [float(row.get("command_overlap") or 0.0) for row in rows]
    new_token_counts = [int(row.get("new_tokens") or 0) for row in rows]
    total_new_tokens = sum(new_token_counts)
    quality = summarize_quality_metrics(rows)
    total_batch_seconds = sum(primary_batch_seconds) + sum(secondary_batch_seconds)
    return {
        "label": "route_selected_final",
        "generation_examples": len(rows),
        "valid_json_rate": round(sum(1 for row in rows if row["schema"]["valid_json"]) / total, 4),
        "schema_valid_rate": round(sum(1 for row in rows if row["schema"]["schema_valid"]) / total, 4),
        "required_field_rate": round(statistics.mean(field_scores) if field_scores else 0.0, 4),
        "command_array_rate": round(sum(1 for row in rows if row["schema"]["commands_valid"]) / total, 4),
        "command_overlap_mean": round(statistics.mean(command_overlaps) if command_overlaps else 0.0, 4),
        "long_command_rate": quality["long_command_rate"],
        "multiline_command_rate": quality["multiline_command_rate"],
        "script_like_command_rate": quality["script_like_command_rate"],
        "risky_command_rate": quality["risky_command_rate"],
        "validation_only_command_rate": quality["validation_only_command_rate"],
        "complete_with_commands_rate": quality["complete_with_commands_rate"],
        "incomplete_without_commands_rate": quality["incomplete_without_commands_rate"],
        "mean_max_command_chars": quality["mean_max_command_chars"],
        "p95_max_command_chars": quality["p95_max_command_chars"],
        "task_complete_bool_rate": round(sum(1 for row in rows if row["schema"]["task_complete_bool"]) / total, 4),
        "sum_batch_generation_seconds": round(total_batch_seconds, 6),
        "mean_amortized_request_seconds": round(total_batch_seconds / total, 6),
        "mean_new_tokens": round(statistics.mean(new_token_counts) if new_token_counts else 0.0, 4),
        "total_new_tokens": total_new_tokens,
        "tokens_per_second": round(total_new_tokens / max(total_batch_seconds, 1e-9), 4),
    }


def render_report(metrics: dict[str, Any]) -> str:
    primary = metrics["results"][0]
    selected = metrics["results"][1]
    route = metrics["route"]
    return "\n".join([
        "# Agent Planner Transformers Route Benchmark",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Profile: `{metrics['run_config']['profile_name']}`",
        f"- Requested secondary: {route['requested_secondary_count']} ({route['requested_secondary_rate']:.2%})",
        f"- Changed from primary: {route['changed_from_primary_count']} ({route['changed_from_primary_rate']:.2%})",
        f"- Secondary rejected: {route.get('secondary_rejected_count', 0)}",
        "",
        "| Route | Schema | Overlap | Long cmd | Script-like | Validation-only | Mean sec |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        format_result("primary", primary),
        format_result("selected", selected),
    ]) + "\n"


def format_result(label: str, row: dict[str, Any]) -> str:
    return (
        f"| {label} | {row['schema_valid_rate']:.2%} | {row['command_overlap_mean']:.4f} | "
        f"{row['long_command_rate']:.2%} | {row['script_like_command_rate']:.2%} | "
        f"{row['validation_only_command_rate']:.2%} | {row['mean_amortized_request_seconds']:.4f}s |"
    )


def cleanup_cuda() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


if __name__ == "__main__":
    main()
