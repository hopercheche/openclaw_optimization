# Agent Planner Transformers Batch Benchmark

- Created at: 2026-06-27T02:06:21.574585Z
- Model: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 1000
- Max new tokens: 272
- Retry invalid max new tokens: 272
- Batch size: 32
- Max batch prompt tokens: None
- Actual batch count: 32
- Device placement: cuda
- Extra output policy: True
- Sort by prompt length: True
- Torch: 2.11.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Result | Schema valid | Mean amortized request | Command overlap | Mean tokens | Tok/s | Retry count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 99.80% | 0.2284s | 0.1594 | 135.03 | 591.21 | 0 |
| final | 100.00% | 0.2304s | 0.1598 | 134.67 | 584.44 | 2 |

## Prompt Padding

- Mean prompt tokens: 837.03
- Max prompt tokens: 1016
- Padding tokens: 13534
- Padding fraction: 1.59%
