# Agent Planner Transformers Batch Benchmark

- Created at: 2026-06-26T13:40:23.781811Z
- Model: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 512
- Max new tokens: 256
- Batch size: 32
- Max batch prompt tokens: None
- Actual batch count: 16
- Device placement: cuda
- Extra output policy: True
- Sort by prompt length: True
- Torch: 2.11.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 99.80% | 0.2284s | 135.20 | 591.82 | 116.9658s | 9751.12 |

## Prompt Padding

- Mean prompt tokens: 843.92
- Max prompt tokens: 1016
- Padding tokens: 14346
- Padding fraction: 3.21%
