# Agent Planner Transformers Batch Benchmark

- Created at: 2026-06-26T08:37:15.354546Z
- Model: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 256
- Max new tokens: 256
- Batch size: 64
- Sort by prompt length: True
- Torch: 2.11.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100.00% | 0.2244s | 127.23 | 566.87 | 57.4557s | 13392.71 |

## Prompt Padding

- Mean prompt tokens: 797.20
- Max prompt tokens: 1016
- Padding tokens: 30029
- Padding fraction: 12.83%
