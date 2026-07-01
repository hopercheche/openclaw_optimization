#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_PLANNER_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_planner_sft import ASSISTANT_MARKER, IM_END, split_sft_text  # noqa: E402


DEFAULT_BASE_MODEL = (
    AGENT_PLANNER_ROOT
    / "models"
    / "20260627T-stage7-verifier-combined3k-500-merged"
)
DEFAULT_ADAPTER = (
    AGENT_PLANNER_ROOT
    / "models"
    / "20260630T-architecture-policy-compact-continue200"
    / "final_adapter"
)


@dataclass(slots=True)
class GenerationExample:
    source: str
    line_number: int
    prompt: str
    target: str
    task_preview: str
    expected: dict[str, Any]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batched generation benchmark for compact OpenClaw architecture-policy adapters.",
    )
    parser.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-label", default="architecture_policy_compact_continue200")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--generation-examples", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--dtype", choices=("bf16", "fp16", "fp32"), default="bf16")
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this benchmark, but torch cannot see a CUDA device.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    examples = load_examples(args.eval_file, start_line=args.start_line, limit=args.generation_examples)
    if not examples:
        raise SystemExit(f"No examples loaded from {args.eval_file}")

    tokenizer = AutoTokenizer.from_pretrained(
        str(args.base_model),
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    model = load_model(args.base_model, args.adapter, args.dtype)
    device = next(model.parameters()).device
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    run_config = {
        "created_at": utc_now(),
        "base_model": str(args.base_model),
        "adapter": str(args.adapter),
        "eval_file": str(args.eval_file),
        "output_dir": str(args.output_dir),
        "model_label": args.model_label,
        "start_line": args.start_line,
        "generation_examples": len(examples),
        "batch_size": args.batch_size,
        "max_seq_length": args.max_seq_length,
        "max_new_tokens": args.max_new_tokens,
        "dtype": args.dtype,
        "require_cuda": args.require_cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "eval_samples.jsonl", [asdict(example) for example in examples])

    metrics, generation_rows = generate_batches(
        model=model,
        tokenizer=tokenizer,
        examples=examples,
        label=args.model_label,
        batch_size=args.batch_size,
        max_seq_length=args.max_seq_length,
        max_new_tokens=args.max_new_tokens,
        device=device,
    )
    peak_memory = (
        round(torch.cuda.max_memory_allocated() / 1024 / 1024, 2)
        if torch.cuda.is_available()
        else None
    )
    metrics.update({
        "created_at": utc_now(),
        "run_config": run_config,
        "gpu_peak_memory_mb": peak_memory,
    })
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "generations.jsonl", generation_rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def load_examples(path: Path, *, start_line: int, limit: int) -> list[GenerationExample]:
    examples: list[GenerationExample] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < start_line or not line.strip():
                continue
            row = json.loads(line)
            text = row.get("text")
            if not isinstance(text, str):
                continue
            split = split_sft_text(text)
            if split is None:
                continue
            prompt, target = split
            examples.append(
                GenerationExample(
                    source=str(row.get("source") or ""),
                    line_number=line_number,
                    prompt=prompt,
                    target=target,
                    task_preview=extract_task_preview(prompt),
                    expected=dict(row.get("expected") or {}),
                )
            )
            if len(examples) >= limit:
                break
    return examples


def load_model(base_model: Path, adapter: Path | None, dtype: str):
    torch_dtype = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }[dtype]
    model = AutoModelForCausalLM.from_pretrained(
        str(base_model),
        torch_dtype=torch_dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
        local_files_only=True,
    )
    if adapter is not None:
        model = PeftModel.from_pretrained(model, str(adapter), local_files_only=True)
    model.eval()
    return model


def generate_batches(
    *,
    model,
    tokenizer,
    examples: list[GenerationExample],
    label: str,
    batch_size: int,
    max_seq_length: int,
    max_new_tokens: int,
    device,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    batch_seconds: list[float] = []
    new_token_counts: list[int] = []
    started_all = time.perf_counter()
    for batch_start in range(0, len(examples), batch_size):
        batch = examples[batch_start:batch_start + batch_size]
        prompt_ids = [
            truncate_prompt(tokenizer, example.prompt, max_prompt_tokens=max_seq_length - 8)
            for example in batch
        ]
        encoded = tokenizer.pad(
            {"input_ids": prompt_ids},
            padding=True,
            return_attention_mask=True,
            return_tensors="pt",
        )
        input_ids = encoded["input_ids"].to(device)
        attention_mask = encoded["attention_mask"].to(device)
        synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        synchronize()
        elapsed = time.perf_counter() - started
        batch_seconds.append(elapsed)
        prompt_width = input_ids.shape[-1]
        for offset, example in enumerate(batch):
            generated_ids = output[offset, prompt_width:]
            generated = tokenizer.decode(generated_ids, skip_special_tokens=False)
            new_tokens = int(generated_ids.shape[-1])
            new_token_counts.append(new_tokens)
            rows.append({
                "model_label": label,
                "line_number": example.line_number,
                "source": example.source,
                "task_preview": example.task_preview,
                "prompt": example.prompt,
                "expected": example.expected,
                "batch_index": batch_start // batch_size,
                "generation_seconds": round(elapsed, 6),
                "amortized_generation_seconds": round(elapsed / max(len(batch), 1), 6),
                "new_tokens": new_tokens,
                "generated_text": generated,
            })
    elapsed_all = time.perf_counter() - started_all
    total_tokens = sum(new_token_counts)
    row_count = len(examples)
    return {
        "rows": row_count,
        "batch_size": batch_size,
        "max_new_tokens": max_new_tokens,
        "total_generation_seconds": round(sum(batch_seconds), 6),
        "wall_seconds": round(elapsed_all, 6),
        "mean_batch_seconds": round(statistics.mean(batch_seconds) if batch_seconds else 0.0, 6),
        "mean_amortized_generation_seconds": (
            round(sum(batch_seconds) / row_count, 6)
            if row_count else 0.0
        ),
        "mean_new_tokens": round(statistics.mean(new_token_counts) if new_token_counts else 0.0, 4),
        "tokens_per_second": round(total_tokens / max(sum(batch_seconds), 1e-9), 4),
    }, rows


def truncate_prompt(tokenizer, prompt: str, *, max_prompt_tokens: int) -> list[int]:
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    return prompt_ids[-max_prompt_tokens:]


def extract_task_preview(prompt: str) -> str:
    marker = "Subtask candidate:"
    index = prompt.find(marker)
    if index >= 0:
        preview = prompt[index + len(marker):]
    else:
        preview = prompt
    return " ".join(preview.split())[:500]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def render_report(metrics: dict[str, Any]) -> str:
    return (
        "# Architecture Policy Model Benchmark\n\n"
        f"- Rows: {metrics['rows']}\n"
        f"- Batch size: {metrics['batch_size']}\n"
        f"- Max new tokens: {metrics['max_new_tokens']}\n"
        f"- Mean amortized generation: {metrics['mean_amortized_generation_seconds']}s\n"
        f"- Tokens/s: {metrics['tokens_per_second']}\n"
        f"- Peak GPU MB: {metrics.get('gpu_peak_memory_mb')}\n"
    )


def synchronize() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
