# Agent Planner Transformers Batch Benchmark

- Created at: 2026-06-26T13:24:21.289086Z
- Model: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 256
- Max new tokens: 256
- Batch size: 48
- Sort by prompt length: True
- Torch: 2.11.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100.00% | 0.2324s | 126.32 | 543.62 | 59.4878s | 11516.53 |

## Prompt Padding

- Mean prompt tokens: 797.20
- Max prompt tokens: 1016
- Padding tokens: 20205
- Padding fraction: 9.01%
