# Agent Planner Transformers Batch Benchmark

- Created at: 2026-06-26T13:29:53.660338Z
- Model: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 256
- Max new tokens: 256
- Batch size: 96
- Max batch prompt tokens: 32768
- Actual batch count: 8
- Sort by prompt length: True
- Torch: 2.11.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100.00% | 0.2406s | 126.36 | 525.22 | 61.5900s | 9642.88 |

## Prompt Padding

- Mean prompt tokens: 797.20
- Max prompt tokens: 1016
- Padding tokens: 23922
- Padding fraction: 10.49%
