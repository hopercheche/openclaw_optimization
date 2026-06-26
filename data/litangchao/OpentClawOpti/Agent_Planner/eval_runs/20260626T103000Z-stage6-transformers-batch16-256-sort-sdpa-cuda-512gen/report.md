# Agent Planner Transformers Batch Benchmark

- Created at: 2026-06-26T13:36:50.498407Z
- Model: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 512
- Max new tokens: 256
- Batch size: 16
- Max batch prompt tokens: None
- Actual batch count: 32
- Device placement: cuda
- Sort by prompt length: True
- Torch: 2.11.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 99.80% | 0.2541s | 126.88 | 499.25 | 130.1221s | 7876.82 |

## Prompt Padding

- Mean prompt tokens: 816.03
- Max prompt tokens: 1016
- Padding tokens: 7280
- Padding fraction: 1.71%
