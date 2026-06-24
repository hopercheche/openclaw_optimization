# Agent Planner Evaluation Summary

Updated: 2026-06-24

## Large SFT Run

```text
run: 20260623T063028Z-qwen25-3b-gpu1-stream200k-5k
base: Qwen2.5-3B-Instruct local cache
adapter: models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter
train_file: processed/qwen_terminal_toolbench_sft.jsonl
samples: 200,000 streaming examples
steps: 5,000 / 5,000
runtime: about 3:31:31
last logged loss at step 5000: 0.3573
```

## Heldout SFT Evaluation

Heldout slice starts at line 300001 of `processed/qwen_terminal_toolbench_sft.jsonl`, outside the first 200k streaming training window.

```text
eval_run: eval_runs/20260623T143655Z-base-vs-lora-heldout
loss_examples: 64
generation_examples: 16
max_new_tokens: 256
gpu: GPU1 / NVIDIA L20
```

| Model | Loss | PPL | Valid JSON | Schema Valid | Mean TTFT | Gen tok/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1.811775 | 6.1213 | 12.50% | 0.00% | 0.0446s | 60.63 |
| LoRA adapter | 1.056539 | 2.8764 | 0.00% | 0.00% | 0.0619s | 27.88 |

Adapter loss improved by 41.68% relative to base, which shows the SFT run learned the heldout token distribution. However, with a 256-token generation budget the adapter often starts with a long `<think>` block and truncates before a complete JSON object.

Adapter-only long-window check:

```text
eval_run: eval_runs/20260623T144420Z-lora-heldout-gen768
generation_examples: 8
max_new_tokens: 768
valid_json_rate: 50.00%
schema_valid_rate: 50.00%
mean_ttft: 0.0966s
mean_generation_seconds: 21.6793s
mean_tokens_per_second: 28.28
```

Conclusion: this adapter is a useful warm-start checkpoint, but it is not yet a fast-response production planner. The next training pass should convert targets to concise JSON-only planner actions, remove or mask `<think>` spans, and evaluate strict schema validity as a first-class metric.

## JSON-Only Optimization Pass

The first LoRA checkpoint was continued through three GPU1 passes:

```text
stage2: JSON-only targets, 200k source rows, 1,000 steps
stage3: strict JSON prompt targets, 100k source rows, 500 steps
stage4: strict JSON prompt + at most 3 commands + shorter action fields, 100k source rows, 500 steps
stage5: stage4 continued on short-command targets, dropping commands with keystrokes longer than 160 chars, 100k source rows, 500 steps
stage6: stage5 continued on compact action2 targets, dropping commands with keystrokes longer than 120 chars, 100k source rows, 500 steps
```

Current recommended adapter:

```text
models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500/final_adapter
```

### Stage Comparison

All rows below use heldout data generated from line 300001 of the original Qwen Terminal ToolBench SFT file. Stage2-4 use the action-level target surface; stage5-6 use progressively shorter command/action target surfaces.

| Run | Eval | Max New Tokens | Gen Examples | Schema Valid | Mean TTFT | Mean Gen Time | Mean Tokens | Gen tok/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stage2 JSON-only | `20260624T080900Z-jsononly-stage2-heldout` | 256 | 16 | 31.25% | 0.0618s | 7.9832s | 226.56 | 28.36 |
| stage3 strict prompt | `20260624T084200Z-strict-json-stage3-heldout` | 256 | 16 | 31.25% | 0.0633s | n/a | 218.69 | 27.78 |
| stage4 action3 | `20260624T101000Z-action3-stage4-heldout` | 256 | 16 | 87.50% | 0.0672s | 7.1978s | 202.00 | 28.04 |
| stage4 action3, wider check | `20260624T103100Z-action3-stage4-heldout-64gen` | 256 | 64 | 76.56% | 0.0767s | 7.2388s | 204.22 | 28.20 |
| stage4 action3, short budget | `20260624T102000Z-action3-stage4-heldout-192` | 192 | 16 | 43.75% | 0.0828s | 6.2234s | 177.31 | 28.48 |
| stage5 shortcmd160 | `20260624T114000Z-shortcmd160-stage5-heldout-64gen` | 256 | 64 | 96.88% | 0.0703s | 5.7663s | 164.28 | 28.49 |
| stage5 shortcmd160, short budget | `20260624T115000Z-shortcmd160-stage5-heldout-192-64gen` | 192 | 64 | 87.50% | 0.0708s | 5.6561s | 159.63 | 28.22 |
| stage6 shortcmd120 action2 | `20260624T133000Z-shortcmd120-action2-stage6-heldout-192-64gen` | 192 | 64 | 96.88% | 0.0708s | 4.6234s | 128.66 | 27.82 |
| stage6 shortcmd120 action2, short budget | `20260624T134000Z-shortcmd120-action2-stage6-heldout-160-64gen` | 160 | 64 | 93.75% | 0.0704s | 4.5087s | 127.11 | 28.19 |

Stage4 is the first checkpoint that consistently produces valid planner-shape JSON under a 256-token budget. The 64-example check is lower than the 16-example run, but still confirms a material jump from the 0-31% schema-valid range seen before the action-level rewrite.

Stage5 is the current best checkpoint. Filtering out commands longer than 160 characters directly addressed the main stage4 failure mode: truncated JSON after the model began writing long heredoc/script commands. On the 64-example check, stage5 improved schema validity from 76.56% to 96.88% and cut mean generation time from 7.2388s to 5.7663s.

The 192-token stage5 check is usable but not recommended as the default: it saves only about 0.11s versus the 256-token run while dropping schema validity from 96.88% to 87.50%.

Stage6 is the new best checkpoint. Reducing the target to at most two short commands, with 120-character command keystroke filtering and 160-character analysis/plan fields, preserved 96.88% schema validity at a 192-token budget and reduced mean generation time to 4.6234s. The 160-token budget is usable but not the default because it saves only about 0.11s while dropping schema validity to 93.75%.

### What Changed

The useful optimization was not more generic SFT. It was changing the target surface:

```text
old target: verbose <think> text followed by JSON
stage2: JSON-only assistant target
stage3: strict JSON output instruction
stage4: action-level JSON with max 3 commands and shorter analysis/plan fields
stage5: short-command JSON, dropping command keystrokes longer than 160 chars
stage6: compact action2 JSON, dropping command keystrokes longer than 120 chars
```

This made the model stop spending most of the token budget on hidden reasoning and move toward a planner action object earlier.

### Next Direction

Do not replace the current OpenClaw planner with this checkpoint yet. Stage6 is now a stronger policy candidate for compact next-actions, but mean generation is still about 4.62s for roughly 129 output tokens on Qwen2.5-3B + LoRA.

The next optimization should be one of:

```text
1. continue stage6 with more compact short-command rows and evaluate at 64+ generation examples each time
2. add constrained JSON/schema decoding so near-miss generations cannot drift outside the planner schema
3. merge the LoRA or serve it with vLLM to measure real serving latency instead of raw Transformers generation
4. distill the stage6 policy into Qwen2.5-1.5B-Instruct or a smaller planner if response speed is the main constraint
```

## OpenClaw Planner Benchmarks

Main deterministic benchmark:

```text
run: openclaw_benchmark_runs/20260623T143948Z-main-deterministic
tasks: 88 x 3 repeats
stop_criteria_met: true
```

| Strategy | Success | Mean Score | Mean Latency | Invalid Tools | Hallucinations | Loops | Unsafe Auto-Allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| greedy_topk | 5.68% | 0.7528 | 0.2884s | 0 | 0 | 0 | 0 |
| audit_astar | 100.00% | 1.0000 | 0.2829s | 0 | 0 | 0 | 0 |
| audit_reflexion | 100.00% | 1.0000 | 0.2948s | 0 | 0 | 0 | 0 |

No-hint control:

```text
tasks: 34 stripped multi-source planner tasks
enabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-enabled
disabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-disabled
```

| Condition | Success | Holdout Success | Mean Score |
| --- | ---: | ---: | ---: |
| learned profile model enabled | 97.06% | 100.00% | 0.9902 |
| learned profile model disabled | 5.88% | 0.00% | 0.7917 |

The existing OpenClaw planner path remains healthy. The new LoRA planner checkpoint is separate from that runtime and should not replace it until the strict JSON/action evaluation is materially better.
