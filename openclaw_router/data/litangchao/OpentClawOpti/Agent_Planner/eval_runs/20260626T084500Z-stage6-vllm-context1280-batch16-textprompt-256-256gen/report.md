# Agent Planner vLLM Benchmark

- Created at: 2026-06-26T08:14:20.844164Z
- Model: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 256
- Max model len: 1280
- Max new tokens: 256
- Prompt token budget: 1024
- Batch size: 16
- Frequency penalty: 0.0
- Repetition penalty: 1.0
- vLLM: 0.18.1
- Torch: 2.10.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 97.66% | 0.1712s | 108.34 | 632.74 | 43.8315s | 0.0 |
