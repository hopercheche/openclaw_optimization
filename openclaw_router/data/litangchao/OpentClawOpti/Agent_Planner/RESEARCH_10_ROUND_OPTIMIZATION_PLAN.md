# Agent Planner 10-Round Optimization Plan

Updated: 2026-06-27

This plan moves the planner-model track beyond batch sizing and token-budget tuning. The current serving baseline is:

```text
model: models/20260625T002525Z-qwen25-3b-stage6-merged
runtime: Transformers on GPU1, bf16, SDPA, direct CUDA placement
default profile: batch32 fast first pass + selective hard retry
1k heldout: 100.00% schema, 0.1525 command overlap, 0.2120s amortized
quality profile: medium compact policy + hard retry
1k heldout: 100.00% schema, 0.1598 command overlap, 0.2304s amortized
```

The next target is not just lower latency. The target is a planner that is faster, more accurate at choosing useful next actions, easier to validate, and trainable from execution feedback.

## Source-Backed Method Map

| Work | Date | Method idea | Why it matters here |
| --- | --- | --- | --- |
| [ToolLLM / ToolBench](https://arxiv.org/abs/2307.16789) | 2023-07 | Tool-use data construction, decision-tree search, ToolEval | Use search/rerank over candidate planner actions instead of single JSON decoding. |
| [API-Bank](https://arxiv.org/abs/2304.08244) | 2023-04 | Tool-use benchmark with planning/retrieval/calling failures | Add failure taxonomy beyond schema validity: retrieval, planning, call correctness. |
| [Reflexion](https://arxiv.org/abs/2303.11366) | 2023-03 | Verbal feedback memory after failed trials | Store compact failure reflections for retry and later SFT examples. |
| [Tree of Thoughts](https://arxiv.org/abs/2305.10601) / [Graph of Thoughts](https://arxiv.org/abs/2308.09687) | 2023 | Search over intermediate plans and aggregate/revise thoughts | Implement bounded plan-candidate search with verifier scoring. |
| [LATS](https://arxiv.org/abs/2310.04406) | 2023-10 | MCTS-like language-agent tree search with self-reflection/value estimates | Build a low-cost K-candidate action search for hard prompts only. |
| [tau-bench](https://arxiv.org/abs/2406.12045) | 2024-06 | Tool-agent-user benchmark, pass^k reliability, final-state verification | Evaluate consistency over repeats, not only one-pass JSON shape. |
| [Agent-as-a-Judge](https://arxiv.org/abs/2410.10934) | 2024-10 | Agentic evaluator that inspects process and environment | Build a local judge/verifier that labels action usefulness and repair causes. |
| [ToolACE-DEV](https://arxiv.org/abs/2505.07512) | 2025-05 | Self-improving tool-learning via decomposition and evolution | Generate target-model-compatible hard examples instead of only distilling stronger models. |
| [Agent-RLVR](https://arxiv.org/abs/2506.11425) | 2025-06 | RLVR for agents with guidance and environment rewards | Train on verifier-guided reattempts after failures, not sparse final rewards alone. |
| [Agent Lightning](https://arxiv.org/abs/2508.03680) | 2025-08 | Decouple agent execution from RL training with transition/credit assignment | Reuse `tau_bench_agent_lightning_transitions.jsonl` and OpenClaw rollouts for RL data. |
| [SkyRL-Agent](https://arxiv.org/abs/2511.16108) | 2025-11 | Async multi-turn RL, tool-enhanced training, AST search | Add tool-aware search/retrieval and async rollout collection later. |
| [AgentGym-RL](https://arxiv.org/abs/2509.08755) | 2025-09 | Multi-turn RL with exploration schedule | Use shorter horizons first, then expand to harder OpenClaw tasks. |

## Ten Innovation Points

1. **Selective Repair Cascade**
   - Idea: Treat schema-invalid output as a recoverable event, not a global prompt problem.
   - Current evidence: 1k heldout first pass reached 99.70% schema; retrying only 3 invalid outputs reached 100.00% at 0.2120s.
   - Next implementation: turn retry policy into a reusable serving config and add per-error retry counters.

2. **Verifier-Guided Candidate Reranking**
   - Idea: Generate 2-4 candidate JSON actions only for hard prompts and choose with deterministic verifiers.
   - Inspired by: ToolLLM decision-tree search, ToT/GoT/LATS.
   - Verifiers: valid JSON, short command policy, no heredoc/multiline, known workspace path, command-risk score, expected terminal-state consistency.

3. **Action Failure Taxonomy and Dense Rewards**
   - Idea: Replace one scalar `schema_valid` with labeled failure causes.
   - Labels: invalid JSON, missing field, long command, validation-only command, risky command, wrong tool, redundant command, task-complete mismatch.
   - Output: `processed/planner_failure_taxonomy_*.jsonl` and reward features for SFT/DPO/RL.

4. **Medium-Policy Distillation**
   - Idea: The medium compact policy improves command overlap but costs latency when applied globally. Distill its behavior into the model so inference can return to the fast first-pass prompt.
   - Data: compare fast output vs medium-policy output; keep pairs where medium improves schema or command quality.
   - Training: stage7 LoRA or DPO preference run.

5. **Guided Reattempt Dataset**
   - Idea: Agent-RLVR-style guidance: let the model fail, attach targeted feedback, then reattempt.
   - Use: failure taxonomy produces feedback such as "do not validate; task is already complete; return empty commands".
   - Training target: successful reattempt JSON.

6. **Skill-Conditioned Self-Distillation**
   - Idea: Summarize successful trajectories into compact reusable skills, then train the planner to internalize them.
   - Skill examples: "when output files already exist and look correct, finish instead of validating", "prefer cat/head over Python validation scripts".
   - Use only at training time; serving prompt stays short.

7. **Tool/Action Affordance Retriever**
   - Idea: Retrieve allowed next-action templates from the terminal state and task type.
   - Fit: Our failures often come from the model inventing validation scripts. A small retriever can bias toward safe actions like `cat`, `ls`, `python3 process.py`, or empty `commands`.
   - Implementation: build a nearest-neighbor index over successful expected commands and task previews.

8. **Risk-Aware Dynamic Planner Routing**
   - Idea: A lightweight router chooses between fast, selective-retry, medium-compact, candidate-search, or deterministic planner fallback.
   - Features: prompt length, recent command pattern, file-output indicators, model confidence proxy, first-pass schema, long-command risk.
   - Metric: lower mean latency at fixed 100% schema and no lower task score.

9. **Agent-as-Judge Process Verifier**
   - Idea: A judge agent evaluates whether the selected action is useful, redundant, risky, or merely validating.
   - Use: offline evaluation and training labels first; online only for uncertain/high-risk cases.
   - Guardrail: calibrate against deterministic checks to avoid Goodharting a single judge.

10. **Serving-Stack-Aware Distillation**
    - Idea: vLLM/SGLang were faster but lower command quality. Instead of switching directly, collect paired outputs from Transformers vs serving stack and distill/repair toward the target stack.
    - Goal: recover Transformers command overlap while using faster serving infrastructure later.
    - Gate: serving stack must match or exceed the Transformers 1k schema/overlap profile before promotion.

## Ten Iteration Rounds

| Round | Innovation focus | Implementation artifact | Primary metric | Gate to continue |
| ---: | --- | --- | --- | --- |
| 1 | Selective repair cascade | Add reusable retry profile config and benchmark support | 1k schema, latency, retry count | Keep 100% schema with <0.215s amortized |
| 2 | Failure taxonomy | `scripts/analyze_planner_failures.py` and taxonomy JSONL | Failure label coverage | >=95% invalid/low-quality rows labeled |
| 3 | Hard-prompt candidate reranking | `scripts/benchmark_planner_rerank.py` | Schema + overlap + candidate cost | Improve overlap over 0.1525 without >10% latency |
| 4 | Medium-policy distillation data | `processed/stage7_medium_policy_pairs.jsonl` | Pair quality, long-command reduction | >=5k high-confidence better pairs |
| 5 | Stage7 SFT/DPO | LoRA adapter and merged checkpoint | 1k schema/overlap, no-hint task score | Beat selective-retry overlap at similar latency |
| 6 | Guided reattempt dataset | failure feedback + successful reattempt JSONL | Repair success by failure type | Reduce long-command failures by >=80% |
| 7 | Agent Lightning / RLVR pilot | transition rewards from OpenClaw/tau-bench | task success/reward, invalid tool rate | Improve no-hint or tau reward without schema loss |
| 8 | Tool/action retriever | command-template retriever + prompt injection or decoder hint | wrong/redundant command rate | Lower redundant validation commands |
| 9 | Dynamic route policy | router over fast/retry/compact/search/fallback | Pareto frontier: latency vs quality | Better than fixed default on mixed eval set |
| 10 | Serving-stack distillation | vLLM/SGLang paired-output repair dataset | serving schema/overlap/latency | Promote only if quality gap closes |

## Evaluation Contract

Every round must report:

```text
heldout generation examples: 1000 when available
schema_valid_rate
command_overlap_mean
mean_amortized_request_seconds
tokens_per_second
retry_count / candidate_count
long_command_rate
validation_only_command_rate
task_complete_bool_rate
OpenClaw no-hint or task-level benchmark when runtime integration is touched
```

Promotion rule:

```text
Do not promote a route on 64-example evidence.
Prefer 1k heldout evidence for planner-model serving.
Prefer task-level OpenClaw/no-hint evidence before replacing deterministic runtime behavior.
Keep fast/quality/fallback profiles separate instead of collapsing them into one setting.
```

## Immediate Next Work

1. Implement Round 2 failure taxonomy first. It unlocks better rewards, better reranking, and better training data.
2. Add `long_command_rate` and `validation_only_command_rate` to benchmark metrics.
3. Build a stage7 training file from cases where medium compact or retry output improves fast output.
4. Run a small stage7 LoRA smoke before a full 100k-row run.

## Round 2 Initial Taxonomy Result

Implemented:

```text
scripts/analyze_planner_failures.py
```

Initial 1k analysis:

| Profile | Schema | Overlap | Low-overlap rate | Long-command rate | Script-like rate | Validation-only rate | Takeaway |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fast + selective hard retry | 100.00% | 0.1525 | 42.60% | 2.30% | 6.20% | 6.70% | current default; fastest reliable route |
| medium compact + hard retry | 100.00% | 0.1598 | 40.90% | 2.40% | 5.40% | 7.10% | better overlap, but validation-only rate is not lower |

Interpretation:

```text
Schema is no longer the main bottleneck.
The next real bottleneck is action usefulness: low command overlap, validation-only commands, and residual script-like commands.
Round 3 should therefore target verifier-guided reranking and training data selection, not more batch tuning.
```
