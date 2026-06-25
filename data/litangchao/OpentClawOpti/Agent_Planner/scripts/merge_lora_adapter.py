#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge a LoRA adapter into a full planner model.")
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dtype", choices=["bf16", "fp16", "fp32"], default="bf16")
    parser.add_argument("--max-shard-size", default="2GB")
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required for merging, but torch cannot see a CUDA device.")
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise SystemExit(f"Output directory is not empty: {args.output_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch_dtype = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }[args.dtype]

    tokenizer_source = args.adapter if (args.adapter / "tokenizer_config.json").exists() else args.base_model
    tokenizer = AutoTokenizer.from_pretrained(
        str(tokenizer_source),
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.save_pretrained(str(args.output_dir))

    base = AutoModelForCausalLM.from_pretrained(
        str(args.base_model),
        torch_dtype=torch_dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
        local_files_only=True,
    )
    model = PeftModel.from_pretrained(base, str(args.adapter), local_files_only=True)
    merged = model.merge_and_unload()
    merged.save_pretrained(
        str(args.output_dir),
        safe_serialization=True,
        max_shard_size=args.max_shard_size,
    )

    merge_config = {
        "created_at": utc_now(),
        "base_model": str(args.base_model),
        "adapter": str(args.adapter),
        "output_dir": str(args.output_dir),
        "dtype": args.dtype,
        "max_shard_size": args.max_shard_size,
        "torch_version": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    (args.output_dir / "merge_config.json").write_text(
        json.dumps(merge_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(merge_config, ensure_ascii=False, indent=2))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
