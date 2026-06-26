# Agent Planner HTTP Benchmark

- Created at: 2026-06-26T08:26:40.486998Z
- Endpoint: `http://127.0.0.1:30080/generate`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260626T084500Z-stage6-vllm-context1280-batch16-textprompt-256-256gen/tokenizer_compat`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 128
- Prompt token budget: 1024
- Max new tokens: 224
- Concurrency: 16

## Results

| Schema valid | Mean amortized request | Mean request | P95 request | Mean tokens | Tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 96.09% | 0.1280s | 1.9647s | 3.3791s | 106.72 | 833.54 |
