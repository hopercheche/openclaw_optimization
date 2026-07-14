#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModel, AutoTokenizer

from evaluate_planner_sft import split_sft_text, utc_now


@dataclass(slots=True)
class EncodedSample:
    line_number: int
    source: str
    input_ids: torch.Tensor
    attention_mask: torch.Tensor
    loss_mask: torch.Tensor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a compact DeepSpec-compatible target cache for OpenClaw planner SFT records."
    )
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--target-model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--deepspec-root",
        type=Path,
        default=Path("data/litangchao/OpentClawOpti/Agent_Planner/external/DeepSpec"),
    )
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--max-samples", type=int, default=128)
    parser.add_argument("--max-length", type=int, default=384)
    parser.add_argument("--min-loss-tokens", type=int, default=14)
    parser.add_argument("--target-layer-ids", default="12,24")
    parser.add_argument("--local-batch-size", type=int, default=4)
    parser.add_argument("--max-shard-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--dtype", choices=["bf16", "fp16", "fp32"], default="bf16")
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required, but torch cannot see a CUDA device.")
    if args.max_samples < 1:
        raise SystemExit("--max-samples must be >= 1")
    if args.max_length < 16:
        raise SystemExit("--max-length must be >= 16")
    if args.local_batch_size < 1:
        raise SystemExit("--local-batch-size must be >= 1")

    target_layer_ids = parse_layer_ids(args.target_layer_ids)
    tokenizer = AutoTokenizer.from_pretrained(
        str(args.target_model),
        trust_remote_code=True,
        local_files_only=True,
    )
    samples = load_encoded_samples(
        args.input_jsonl,
        tokenizer=tokenizer,
        start_line=args.start_line,
        max_samples=args.max_samples,
        max_length=args.max_length,
        min_loss_tokens=args.min_loss_tokens,
    )
    if not samples:
        raise SystemExit("No valid planner SFT samples were encoded.")

    config_payload = load_target_config_payload(args.target_model)
    hidden_size = int(config_payload["hidden_size"])
    estimate = estimate_cache_size(
        samples,
        hidden_size=hidden_size,
        num_target_layers=len(target_layer_ids),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_config = {
        "created_at": utc_now(),
        "input_jsonl": str(args.input_jsonl),
        "target_model": str(args.target_model),
        "output_dir": str(args.output_dir),
        "deepspec_root": str(args.deepspec_root),
        "start_line": args.start_line,
        "max_samples": args.max_samples,
        "encoded_samples": len(samples),
        "max_length": args.max_length,
        "min_loss_tokens": args.min_loss_tokens,
        "target_layer_ids": target_layer_ids,
        "local_batch_size": args.local_batch_size,
        "dtype": args.dtype,
        "estimate_only": args.estimate_only,
        "target_config": {
            key: config_payload.get(key)
            for key in (
                "model_type",
                "architectures",
                "hidden_size",
                "num_hidden_layers",
                "vocab_size",
            )
        },
        "estimate": estimate,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_sample_manifest(args.output_dir / "samples_preview.jsonl", samples[: min(32, len(samples))])
    if args.estimate_only:
        print(json.dumps({"run_config": run_config}, ensure_ascii=False, indent=2))
        return

    deepspec_root = args.deepspec_root.resolve()
    if not (deepspec_root / "deepspec").exists():
        raise SystemExit(f"DeepSpec root is missing deepspec package: {deepspec_root}")
    sys.path.insert(0, str(deepspec_root))
    from deepspec.data.target_cache_dataset import (  # type: ignore
        AsyncTargetCacheWriter,
        LocalCacheWriteSummary,
        build_global_target_cache_shard_map,
        build_target_cache_manifest,
        cleanup_target_cache_tmp_dir,
        finalize_target_cache_index,
        prepare_target_cache_output_dir,
        rename_local_target_cache_shards,
        write_target_cache_manifest,
    )

    cache_dir = args.output_dir / "target_cache"
    prepare_target_cache_output_dir(str(cache_dir))
    rank_dir = cache_dir / "_tmp" / "rank_0"
    rank_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch_dtype = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }[args.dtype]
    target_model = AutoModel.from_pretrained(
        str(args.target_model),
        torch_dtype=torch_dtype,
        attn_implementation="sdpa",
        trust_remote_code=True,
        local_files_only=True,
    ).to(device=device).eval()

    writer = AsyncTargetCacheWriter(
        rank_dir=str(rank_dir),
        max_shard_bytes=int(args.max_shard_bytes),
        max_queue_size=max(8, args.local_batch_size * 4),
    )
    processed = 0
    try:
        for batch in iter_batches(samples, args.local_batch_size):
            batch_tensors = pad_batch(batch, device=device)
            result = run_target_forward_with_hooks(
                target_model=target_model,
                input_ids=batch_tensors["input_ids"],
                attention_mask=batch_tensors["attention_mask"],
                target_layer_ids=target_layer_ids,
            )
            for row_idx, sample in enumerate(batch):
                seq_len = int(sample.input_ids.shape[0])
                writer.write_sample(
                    input_ids=sample.input_ids,
                    attention_mask=sample.attention_mask,
                    loss_mask=sample.loss_mask,
                    target_hidden_states=result["target_hidden_states"][row_idx, :seq_len, :],
                    target_last_hidden_states=result["target_last_hidden_states"][row_idx, :seq_len, :],
                )
                processed += 1
    finally:
        writer.close()

    summary = LocalCacheWriteSummary(
        global_rank=0,
        source_sample_start=0,
        source_sample_end=processed,
        num_local_samples=processed,
        num_local_shards=len(writer.local_shard_files),
        local_shard_files=list(writer.local_shard_files),
    ).to_json()
    (rank_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shard_map, shards = build_global_target_cache_shard_map([summary])
    rename_local_target_cache_shards(
        output_dir=str(cache_dir),
        rank_dir=str(rank_dir),
        summary=summary,
        shard_map=shard_map,
    )
    num_samples = finalize_target_cache_index(
        output_dir=str(cache_dir),
        summaries=[summary],
        shard_map=shard_map,
    )
    manifest = build_target_cache_manifest(
        num_samples=num_samples,
        shards=shards,
        target_layer_ids=target_layer_ids,
        hidden_size=hidden_size,
        extra_fields={
            "target_model_name_or_path": str(args.target_model),
            "source_jsonl_paths": [str(args.input_jsonl)],
            "chat_template": "openclaw_direct_sft_text",
            "max_length": int(args.max_length),
            "min_loss_tokens": int(args.min_loss_tokens),
            "project_name": "openclaw_agent_planner",
            "exp_name": "stage11_deepspec_planner_cache",
            "created_at": utc_now(),
            "encoded_samples": len(samples),
            "cache_estimate": estimate,
        },
    )
    write_target_cache_manifest(output_dir=str(cache_dir), manifest=manifest)
    cleanup_target_cache_tmp_dir(str(cache_dir))
    print(json.dumps({"cache_dir": str(cache_dir), "manifest": manifest}, ensure_ascii=False, indent=2))


def parse_layer_ids(value: str) -> list[int]:
    layer_ids = []
    for item in value.split(","):
        item = item.strip()
        if item:
            layer_ids.append(int(item))
    if not layer_ids:
        raise SystemExit("--target-layer-ids cannot be empty")
    if layer_ids != sorted(layer_ids):
        raise SystemExit("--target-layer-ids must be sorted")
    return layer_ids


def load_target_config_payload(model_path: Path) -> dict[str, Any]:
    config_path = model_path / "config.json"
    if not config_path.exists():
        raise SystemExit(f"Missing target config: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_encoded_samples(
    path: Path,
    *,
    tokenizer,
    start_line: int,
    max_samples: int,
    max_length: int,
    min_loss_tokens: int,
) -> list[EncodedSample]:
    samples: list[EncodedSample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < start_line:
                continue
            payload = json.loads(line)
            text = payload.get("text")
            if not isinstance(text, str):
                continue
            split = split_sft_text(text)
            if split is None:
                continue
            prompt, target = split
            encoded = encode_direct_sft_text(
                tokenizer,
                prompt=prompt,
                target=target,
                max_length=max_length,
            )
            if int(encoded.loss_mask.sum().item()) < min_loss_tokens:
                continue
            samples.append(
                EncodedSample(
                    line_number=line_number,
                    source=str(payload.get("source", "")),
                    input_ids=encoded.input_ids,
                    attention_mask=encoded.attention_mask,
                    loss_mask=encoded.loss_mask,
                )
            )
            if len(samples) >= max_samples:
                break
    return samples


def encode_direct_sft_text(tokenizer, *, prompt: str, target: str, max_length: int) -> EncodedSample:
    prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
    target_ids = tokenizer.encode(target, add_special_tokens=False)
    if len(target_ids) > max_length:
        target_ids = target_ids[:max_length]
        prompt_ids = []
    else:
        prompt_budget = max_length - len(target_ids)
        if len(prompt_ids) > prompt_budget:
            prompt_ids = prompt_ids[-prompt_budget:]
    input_ids = prompt_ids + target_ids
    loss_mask = [0] * len(prompt_ids) + [1] * len(target_ids)
    return EncodedSample(
        line_number=0,
        source="",
        input_ids=torch.tensor(input_ids, dtype=torch.long),
        attention_mask=torch.ones(len(input_ids), dtype=torch.long),
        loss_mask=torch.tensor(loss_mask, dtype=torch.long),
    )


def estimate_cache_size(
    samples: list[EncodedSample],
    *,
    hidden_size: int,
    num_target_layers: int,
) -> dict[str, Any]:
    total_seq_len = sum(int(sample.input_ids.shape[0]) for sample in samples)
    bytes_per_token = {
        "input_ids": 4,
        "attention_mask": 1,
        "loss_mask": 1,
        "target_hidden_states": 2 * int(hidden_size) * int(num_target_layers),
        "target_last_hidden_states": 2 * int(hidden_size),
    }
    total_bytes = total_seq_len * sum(bytes_per_token.values())
    seq_lengths = [int(sample.input_ids.shape[0]) for sample in samples]
    return {
        "sample_count": len(samples),
        "total_seq_len": total_seq_len,
        "mean_seq_len": round(total_seq_len / max(len(samples), 1), 2),
        "max_seq_len": max(seq_lengths) if seq_lengths else 0,
        "hidden_size": int(hidden_size),
        "num_target_layers": int(num_target_layers),
        "bytes_per_token": bytes_per_token,
        "estimated_cache_bytes": total_bytes,
        "estimated_cache_gib": round(total_bytes / 1024**3, 4),
    }


def iter_batches(samples: list[EncodedSample], batch_size: int):
    for start in range(0, len(samples), batch_size):
        yield samples[start:start + batch_size]


def pad_batch(batch: list[EncodedSample], *, device: torch.device) -> dict[str, torch.Tensor]:
    max_len = max(int(sample.input_ids.shape[0]) for sample in batch)
    input_ids = []
    attention_mask = []
    for sample in batch:
        pad_len = max_len - int(sample.input_ids.shape[0])
        input_ids.append(torch.cat([sample.input_ids, torch.zeros(pad_len, dtype=torch.long)]))
        attention_mask.append(torch.cat([sample.attention_mask, torch.zeros(pad_len, dtype=torch.long)]))
    return {
        "input_ids": torch.stack(input_ids).to(device),
        "attention_mask": torch.stack(attention_mask).to(device),
    }


def get_target_backbone(target_model):
    return getattr(target_model, "model", target_model)


def get_hook_tensor(output):
    if isinstance(output, torch.Tensor):
        return output
    if isinstance(output, (tuple, list)) and output and isinstance(output[0], torch.Tensor):
        return output[0]
    raise TypeError(f"Unsupported target hook output type: {type(output)!r}")


@torch.inference_mode()
def run_target_forward_with_hooks(
    *,
    target_model,
    input_ids: torch.Tensor,
    attention_mask: torch.Tensor,
    target_layer_ids: list[int],
) -> dict[str, torch.Tensor]:
    backbone = get_target_backbone(target_model)
    captured: dict[int, torch.Tensor] = {}
    handles = []

    def capture(layer_id: int):
        def hook(_module, _inputs, output):
            captured[layer_id] = get_hook_tensor(output).detach()

        return hook

    try:
        for layer_id in target_layer_ids:
            if layer_id == -1:
                handles.append(backbone.embed_tokens.register_forward_hook(capture(layer_id)))
            else:
                handles.append(backbone.layers[int(layer_id)].register_forward_hook(capture(layer_id)))
        output = target_model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            output_hidden_states=False,
            use_cache=False,
        )
        target_last_hidden_states = output.last_hidden_state.detach()
        target_hidden_states = torch.cat(
            [captured[int(layer_id)] for layer_id in target_layer_ids],
            dim=-1,
        )
    finally:
        for handle in handles:
            handle.remove()
    return {
        "target_hidden_states": target_hidden_states,
        "target_last_hidden_states": target_last_hidden_states,
    }


def write_sample_manifest(path: Path, samples: list[EncodedSample]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(
                    {
                        "line_number": sample.line_number,
                        "source": sample.source,
                        "seq_len": int(sample.input_ids.shape[0]),
                        "loss_tokens": int(sample.loss_mask.sum().item()),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
