#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from evaluate_planner_sft import (
    command_tokens,
    load_examples,
    parse_planner_json,
    score_schema,
    token_jaccard,
    truncate_prompt,
    utc_now,
    write_jsonl,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark batched Transformers generation for a merged planner model.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=None)
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--generation-examples", type=int, default=64)
    parser.add_argument(
        "--extra-output-policy",
        default=None,
        help="Optional extra instruction inserted before the assistant generation marker.",
    )
    parser.add_argument(
        "--retry-invalid-extra-output-policy",
        default=None,
        help="Optional extra output policy used to retry only first-pass schema-invalid generations.",
    )
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument(
        "--retry-invalid-max-new-tokens",
        type=int,
        default=None,
        help="Max new tokens for invalid-output retries. Defaults to --max-new-tokens.",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--max-batch-prompt-tokens",
        type=int,
        default=None,
        help="Optional padded prompt-token budget per batch; keeps batch-size as the hard sequence cap.",
    )
    parser.add_argument("--dtype", choices=["bf16", "fp16", "fp32"], default="bf16")
    parser.add_argument(
        "--attn-implementation",
        choices=["eager", "sdpa", "flash_attention_2"],
        default=None,
        help="Optional Transformers attention backend override.",
    )
    parser.add_argument(
        "--device-placement",
        choices=["auto", "cuda"],
        default="auto",
        help="Use Transformers device_map=auto or place the full model directly on the visible CUDA device.",
    )
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument(
        "--sort-by-prompt-length",
        action="store_true",
        help="Group similarly sized prompts into batches to reduce left-padding work.",
    )
    args = parser.parse_args()

    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this benchmark, but torch cannot see a CUDA device.")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    if args.max_batch_prompt_tokens is not None and args.max_batch_prompt_tokens < 1:
        raise SystemExit("--max-batch-prompt-tokens must be >= 1")
    if args.retry_invalid_max_new_tokens is not None and args.retry_invalid_max_new_tokens < 1:
        raise SystemExit("--retry-invalid-max-new-tokens must be >= 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    examples = load_examples(args.eval_file, args.start_line, args.generation_examples)
    if not examples:
        raise SystemExit(f"No valid examples found in {args.eval_file} starting at line {args.start_line}")

    tokenizer_path = args.tokenizer or args.model
    tokenizer = AutoTokenizer.from_pretrained(
        str(tokenizer_path),
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    model = load_model(args.model, args.dtype, args.attn_implementation, args.device_placement)
    device = next(model.parameters()).device
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    prepared_examples = prepare_examples(
        examples,
        tokenizer=tokenizer,
        max_prompt_tokens=max(1, args.max_seq_length - 8),
        sort_by_prompt_length=args.sort_by_prompt_length,
        extra_output_policy=args.extra_output_policy,
    )
    prepared_batches = make_batches(
        prepared_examples,
        batch_size=args.batch_size,
        max_batch_prompt_tokens=args.max_batch_prompt_tokens,
    )
    prompt_lengths = [len(item["prompt_ids"]) for item in prepared_examples]
    batch_prompt_lengths = [
        [len(item["prompt_ids"]) for item in batch_items]
        for batch_items in prepared_batches
    ]
    padding_stats = summarize_padding(batch_prompt_lengths)
    actual_batch_sizes = [len(batch_items) for batch_items in prepared_batches]

    run_config = {
        "created_at": utc_now(),
        "model": str(args.model),
        "tokenizer": str(tokenizer_path),
        "eval_file": str(args.eval_file),
        "output_dir": str(args.output_dir),
        "start_line": args.start_line,
        "generation_examples": len(examples),
        "extra_output_policy": args.extra_output_policy,
        "retry_invalid_extra_output_policy": args.retry_invalid_extra_output_policy,
        "max_seq_length": args.max_seq_length,
        "max_new_tokens": args.max_new_tokens,
        "retry_invalid_max_new_tokens": args.retry_invalid_max_new_tokens,
        "batch_size": args.batch_size,
        "max_batch_prompt_tokens": args.max_batch_prompt_tokens,
        "actual_batch_count": len(prepared_batches),
        "actual_batch_sizes": actual_batch_sizes,
        "dtype": args.dtype,
        "attn_implementation": args.attn_implementation,
        "device_placement": args.device_placement,
        "require_cuda": args.require_cuda,
        "sort_by_prompt_length": args.sort_by_prompt_length,
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

    benchmark_started = time.perf_counter()
    rows, batch_seconds = run_generation_batches(
        model=model,
        tokenizer=tokenizer,
        device=device,
        prepared_batches=prepared_batches,
        max_new_tokens=args.max_new_tokens,
        pass_name="base",
    )

    total_generation_seconds = time.perf_counter() - benchmark_started
    total_examples = len(examples) or 1
    base_result = summarize_rows(
        rows,
        label=f"transformers_batch{args.batch_size}",
        total_examples=total_examples,
        total_generation_seconds=total_generation_seconds,
        batch_seconds=batch_seconds,
        prompt_lengths=prompt_lengths,
        padding_stats=padding_stats,
    )

    final_rows = rows
    retry_rows: list[dict[str, Any]] = []
    retry_batch_seconds: list[float] = []
    if args.retry_invalid_extra_output_policy:
        retry_items = build_retry_items(
            examples,
            rows,
            tokenizer=tokenizer,
            max_prompt_tokens=max(1, args.max_seq_length - 8),
            extra_output_policy=args.retry_invalid_extra_output_policy,
        )
        if retry_items:
            retry_batches = make_batches(
                retry_items,
                batch_size=args.batch_size,
                max_batch_prompt_tokens=args.max_batch_prompt_tokens,
            )
            retry_rows, retry_batch_seconds = run_generation_batches(
                model=model,
                tokenizer=tokenizer,
                device=device,
                prepared_batches=retry_batches,
                max_new_tokens=args.retry_invalid_max_new_tokens or args.max_new_tokens,
                pass_name="retry_invalid",
            )
            final_rows = merge_retry_rows(rows, retry_rows)

    final_batch_seconds = batch_seconds + retry_batch_seconds
    final_total_generation_seconds = time.perf_counter() - benchmark_started
    final_result = summarize_rows(
        final_rows,
        label=f"transformers_batch{args.batch_size}_final",
        total_examples=total_examples,
        total_generation_seconds=final_total_generation_seconds,
        batch_seconds=final_batch_seconds,
        prompt_lengths=prompt_lengths,
        padding_stats=padding_stats,
    )
    final_result["retry_invalid_count"] = len(retry_rows)
    final_result["retry_generation_seconds"] = round(sum(retry_batch_seconds), 6)
    metrics = {
        "created_at": utc_now(),
        "run_config": run_config,
        "results": [base_result, final_result],
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "generations.jsonl", final_rows)
    if retry_rows:
        write_jsonl(args.output_dir / "retry_generations.jsonl", retry_rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def run_generation_batches(
    *,
    model,
    tokenizer,
    device,
    prepared_batches: list[list[dict[str, Any]]],
    max_new_tokens: int,
    pass_name: str,
) -> tuple[list[dict[str, Any]], list[float]]:
    rows: list[dict[str, Any]] = []
    batch_seconds: list[float] = []
    for batch_items in prepared_batches:
        batch_examples = [item["example"] for item in batch_items]
        batch_prompt_ids = [item["prompt_ids"] for item in batch_items]
        input_tensor, attention_mask = pad_batch(
            batch_prompt_ids,
            pad_token_id=tokenizer.pad_token_id,
            device=device,
        )

        synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(
                input_ids=input_tensor,
                attention_mask=attention_mask,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        synchronize()
        elapsed = time.perf_counter() - started
        batch_seconds.append(elapsed)

        prompt_width = input_tensor.shape[-1]
        for index, item in enumerate(batch_items):
            example = item["example"]
            raw_new_ids = output[index, prompt_width:].tolist()
            new_ids = trim_after_generation_stop(
                raw_new_ids,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
            generated = tokenizer.decode(new_ids, skip_special_tokens=False)
            parsed = parse_planner_json(generated)
            schema = score_schema(parsed)
            expected_commands = command_tokens(example.expected_json)
            predicted_commands = command_tokens(parsed)
            command_overlap = token_jaccard(expected_commands, predicted_commands)

            rows.append({
                "pass": pass_name,
                "original_index": item["original_index"],
                "line_number": example.line_number,
                "source": example.source,
                "task_preview": example.task_preview,
                "batch_size": len(batch_examples),
                "prompt_tokens": len(item["prompt_ids"]),
                "batch_generation_seconds": round(elapsed, 6),
                "amortized_request_seconds": round(elapsed / max(len(batch_examples), 1), 6),
                "new_tokens": len(new_ids),
                "schema": schema,
                "command_overlap": round(command_overlap, 4),
                "expected_commands": sorted(expected_commands),
                "predicted_commands": sorted(predicted_commands),
                "generated_text": generated,
            })
    return rows, batch_seconds


def summarize_rows(
    rows: list[dict[str, Any]],
    *,
    label: str,
    total_examples: int,
    total_generation_seconds: float,
    batch_seconds: list[float],
    prompt_lengths: list[int],
    padding_stats: dict[str, Any],
) -> dict[str, Any]:
    field_scores = [row["schema"]["required_field_fraction"] for row in rows]
    command_overlaps = [row["command_overlap"] for row in rows]
    new_token_counts = [row["new_tokens"] for row in rows]
    total_new_tokens = sum(new_token_counts)
    return {
        "label": label,
        "generation_examples": len(rows),
        "valid_json_rate": round(
            sum(1 for row in rows if row["schema"]["valid_json"]) / total_examples,
            4,
        ),
        "schema_valid_rate": round(
            sum(1 for row in rows if row["schema"]["schema_valid"]) / total_examples,
            4,
        ),
        "required_field_rate": round(statistics.mean(field_scores) if field_scores else 0.0, 4),
        "command_array_rate": round(
            sum(1 for row in rows if row["schema"]["commands_valid"]) / total_examples,
            4,
        ),
        "command_overlap_mean": round(statistics.mean(command_overlaps) if command_overlaps else 0.0, 4),
        "task_complete_bool_rate": round(
            sum(1 for row in rows if row["schema"]["task_complete_bool"]) / total_examples,
            4,
        ),
        "total_generation_seconds": round(total_generation_seconds, 6),
        "sum_batch_generation_seconds": round(sum(batch_seconds), 6),
        "mean_batch_generation_seconds": round(statistics.mean(batch_seconds) if batch_seconds else 0.0, 6),
        "mean_amortized_request_seconds": round(sum(batch_seconds) / total_examples, 6),
        "mean_new_tokens": round(statistics.mean(new_token_counts) if new_token_counts else 0.0, 4),
        "total_new_tokens": total_new_tokens,
        "tokens_per_second": round(total_new_tokens / max(sum(batch_seconds), 1e-9), 4),
        "prompt_tokens_mean": round(statistics.mean(prompt_lengths) if prompt_lengths else 0.0, 4),
        "prompt_tokens_max": max(prompt_lengths) if prompt_lengths else 0,
        "prompt_padding_tokens": padding_stats["padding_tokens"],
        "prompt_padding_fraction": padding_stats["padding_fraction"],
        "gpu_peak_memory_mb": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 2)
        if torch.cuda.is_available()
        else None,
    }


def build_retry_items(
    examples,
    rows: list[dict[str, Any]],
    *,
    tokenizer,
    max_prompt_tokens: int,
    extra_output_policy: str,
) -> list[dict[str, Any]]:
    retry_items: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item["original_index"]):
        if row["schema"]["schema_valid"]:
            continue
        original_index = row["original_index"]
        example = examples[original_index]
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


def merge_retry_rows(base_rows: list[dict[str, Any]], retry_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    retry_by_index = {row["original_index"]: row for row in retry_rows}
    merged: list[dict[str, Any]] = []
    for row in base_rows:
        retry_row = retry_by_index.get(row["original_index"])
        if retry_row is None:
            merged.append(row)
        else:
            updated = dict(retry_row)
            updated["retried_from"] = row
            merged.append(updated)
    return merged


def load_model(model_path: Path, dtype: str, attn_implementation: str | None, device_placement: str):
    torch_dtype = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }[dtype]
    model_kwargs = {}
    if attn_implementation:
        model_kwargs["attn_implementation"] = attn_implementation
    if device_placement == "cuda" and torch.cuda.is_available():
        model = AutoModelForCausalLM.from_pretrained(
            str(model_path),
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            local_files_only=True,
            **model_kwargs,
        )
        model.to("cuda")
    else:
        model = AutoModelForCausalLM.from_pretrained(
            str(model_path),
            torch_dtype=torch_dtype,
            device_map="auto" if torch.cuda.is_available() else None,
            trust_remote_code=True,
            local_files_only=True,
            **model_kwargs,
        )
    model.eval()
    return model


def prepare_examples(
    examples,
    *,
    tokenizer,
    max_prompt_tokens: int,
    sort_by_prompt_length: bool,
    extra_output_policy: str | None,
) -> list[dict[str, Any]]:
    prepared = [
        {
            "original_index": index,
            "example": example,
            "prompt_ids": truncate_prompt(
                tokenizer,
                apply_extra_output_policy(example.prompt, extra_output_policy),
                max_prompt_tokens=max_prompt_tokens,
            ),
        }
        for index, example in enumerate(examples)
    ]
    if sort_by_prompt_length:
        prepared.sort(key=lambda item: len(item["prompt_ids"]))
    return prepared


def apply_extra_output_policy(prompt: str, extra_output_policy: str | None) -> str:
    if not extra_output_policy:
        return prompt
    marker = "<|im_start|>assistant\n"
    policy = extra_output_policy.strip()
    if not policy:
        return prompt
    insertion = f"\nAdditional planner constraints:\n{policy}\n"
    if prompt.endswith(marker):
        return prompt[:-len(marker)] + insertion + marker
    return prompt + insertion


def make_batches(
    prepared_examples: list[dict[str, Any]],
    *,
    batch_size: int,
    max_batch_prompt_tokens: int | None,
) -> list[list[dict[str, Any]]]:
    if max_batch_prompt_tokens is None:
        return [
            prepared_examples[start:start + batch_size]
            for start in range(0, len(prepared_examples), batch_size)
        ]

    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_max = 0
    for item in prepared_examples:
        item_length = len(item["prompt_ids"])
        next_max = max(current_max, item_length)
        next_size = len(current) + 1
        would_exceed_count = next_size > batch_size
        would_exceed_tokens = next_max * next_size > max_batch_prompt_tokens
        if current and (would_exceed_count or would_exceed_tokens):
            batches.append(current)
            current = []
            current_max = 0
            next_max = item_length
        current.append(item)
        current_max = max(current_max, item_length)
    if current:
        batches.append(current)
    return batches


def summarize_padding(batch_prompt_lengths: list[list[int]]) -> dict[str, Any]:
    total_padded = 0
    total_real = 0
    for batch_lengths in batch_prompt_lengths:
        if not batch_lengths:
            continue
        total_real += sum(batch_lengths)
        total_padded += max(batch_lengths) * len(batch_lengths)
    padding_tokens = total_padded - total_real
    return {
        "total_prompt_tokens": total_real,
        "total_padded_prompt_tokens": total_padded,
        "padding_tokens": padding_tokens,
        "padding_fraction": round(padding_tokens / max(total_padded, 1), 4),
    }


def pad_batch(prompt_ids: list[list[int]], *, pad_token_id: int, device) -> tuple[torch.Tensor, torch.Tensor]:
    max_length = max(len(ids) for ids in prompt_ids)
    padded: list[list[int]] = []
    masks: list[list[int]] = []
    for ids in prompt_ids:
        pad_count = max_length - len(ids)
        padded.append([pad_token_id] * pad_count + ids)
        masks.append([0] * pad_count + [1] * len(ids))
    return (
        torch.tensor(padded, dtype=torch.long, device=device),
        torch.tensor(masks, dtype=torch.long, device=device),
    )


def trim_after_generation_stop(new_ids: list[int], *, eos_token_id: int | None, pad_token_id: int | None) -> list[int]:
    trimmed: list[int] = []
    for token_id in new_ids:
        if pad_token_id is not None and token_id == pad_token_id and trimmed:
            break
        trimmed.append(token_id)
        if eos_token_id is not None and token_id == eos_token_id:
            break
    return trimmed


def render_report(metrics: dict[str, Any]) -> str:
    config = metrics["run_config"]
    base_result = metrics["results"][0]
    result = metrics["results"][-1]
    retry_count = result.get("retry_invalid_count", 0)
    return "\n".join([
        "# Agent Planner Transformers Batch Benchmark",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Model: `{config['model']}`",
        f"- Tokenizer: `{config['tokenizer']}`",
        f"- Eval file: `{config['eval_file']}`",
        f"- Generation examples: {config['generation_examples']}",
        f"- Max new tokens: {config['max_new_tokens']}",
        f"- Retry invalid max new tokens: {config['retry_invalid_max_new_tokens']}",
        f"- Batch size: {config['batch_size']}",
        f"- Max batch prompt tokens: {config['max_batch_prompt_tokens']}",
        f"- Actual batch count: {config['actual_batch_count']}",
        f"- Device placement: {config['device_placement']}",
        f"- Extra output policy: {bool(config['extra_output_policy'])}",
        f"- Sort by prompt length: {config['sort_by_prompt_length']}",
        f"- Torch: {config['torch_version']} / CUDA {config['torch_cuda']}",
        f"- Device: {config['device_name']}",
        "",
        "## Results",
        "",
        "| Result | Schema valid | Mean amortized request | Command overlap | Mean tokens | Tok/s | Retry count |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| base | {base_result['schema_valid_rate']:.2%} | "
        f"{base_result['mean_amortized_request_seconds']:.4f}s | "
        f"{base_result['command_overlap_mean']:.4f} | {base_result['mean_new_tokens']:.2f} | "
        f"{base_result['tokens_per_second']:.2f} | 0 |",
        f"| final | {result['schema_valid_rate']:.2%} | {result['mean_amortized_request_seconds']:.4f}s | "
        f"{result['command_overlap_mean']:.4f} | "
        f"{result['mean_new_tokens']:.2f} | {result['tokens_per_second']:.2f} | "
        f"{retry_count} |",
        "",
        "## Prompt Padding",
        "",
        f"- Mean prompt tokens: {result['prompt_tokens_mean']:.2f}",
        f"- Max prompt tokens: {result['prompt_tokens_max']}",
        f"- Padding tokens: {result['prompt_padding_tokens']}",
        f"- Padding fraction: {result['prompt_padding_fraction']:.2%}",
    ]) + "\n"


def synchronize() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


if __name__ == "__main__":
    main()
