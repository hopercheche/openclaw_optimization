# Agent Planner Transformers Batch Benchmark

- Created at: 2026-06-25T03:47:28.152120Z
- Model: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Tokenizer: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 64
- Max new tokens: 192
- Batch size: 16
- Torch: 2.11.0+cu128 / CUDA 12.8
- Device: NVIDIA L20

## Results

| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100.00% | 0.4462s | 123.97 | 277.85 | 28.5549s | 7775.01 |
