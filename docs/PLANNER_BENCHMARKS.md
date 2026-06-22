# Planner Benchmark Notes

Last updated: 2026-06-18

## Reliable External Benchmarks

| Benchmark | What it measures | Why it matters for OpenClaw planner |
| --- | --- | --- |
| [PlanBench](https://arxiv.org/abs/2206.10498) | Classical-style planning and reasoning about action/change | Good source for explicit planning constraints and plan-validity checks. |
| [AgentBench](https://arxiv.org/abs/2308.03688) | LLM agents across 8 interactive environments | Useful failure taxonomy: long-term reasoning, decision-making, and instruction-following failures. |
| [WebArena](https://arxiv.org/abs/2307.13854) | Long-horizon web-agent task completion in realistic sites | Good model for functional task success, grounding, and long-horizon failure measurement. |
| [TravelPlanner](https://arxiv.org/abs/2402.01622) | Real-world planning with tools, constraints, and reference plans | Strong reference for multi-constraint plan validity and tool-choice mistakes. |
| [tau-bench](https://arxiv.org/abs/2406.12045) | Tool-agent-user interaction under domain policies, evaluated by final state | Best reference for policy/rule following and pass^k reliability. |
| [API-Bank](https://arxiv.org/abs/2304.08244) | Tool-augmented LLM planning/retrieval/API calls | Useful for API-call sequencing and tool-use error categories. |
| [ToolBench / ToolLLM](https://arxiv.org/abs/2307.16789) | Real-world API tool use and solution-path search | Useful for multi-tool path evaluation. |
| [StableToolBench](https://arxiv.org/abs/2403.07714) | Stable tool-learning benchmark with virtual APIs and solvable/win rates | Good reason to prefer deterministic local tool simulators over live APIs for repeatable evaluation. |

## Local Benchmark Design

OpenClaw's local benchmark borrows the reliable parts of these benchmarks without importing their heavy environments:

- PlanBench: explicit expected tools, forbidden tools, required events, and permission outcomes.
- tau-bench: policy correctness through allow/ask/deny behavior and unsafe auto-allow checks.
- ToolBench/API-Bank: tool path validity, invalid tool calls, and sequencing.
- WebArena/TravelPlanner: long-horizon task framing and constraint coverage.
- StableToolBench: deterministic local workspaces and simulated tool effects.

## Implemented Framework

Files:

- `backend/openclaw/benchmark.py`
- `backend/openclaw/model_matrix.py`
- `benchmarks/tasks/*.json`
- `benchmarks/model_matrix.example.json`
- `data/benchmarks/{timestamp}/metrics.json`
- `data/benchmarks/{timestamp}/report.md`
- `data/model_matrix/{timestamp}/matrix_metrics.json`
- `data/model_matrix/{timestamp}/matrix_report.md`

Default command:

```bash
.venv/bin/python backend/openclaw/benchmark.py --repeats 3
```

Compare selected strategies:

```bash
.venv/bin/python backend/openclaw/benchmark.py --strategies greedy_topk,audit_astar
```

Use a fixed output directory:

```bash
.venv/bin/python backend/openclaw/benchmark.py --output-dir /tmp/openclaw_benchmark
```

Run with the detected AgentScope/model runtime:

```bash
.venv/bin/python backend/openclaw/benchmark.py --runtime as2 --repeats 3
```

`--runtime deterministic` is the default and uses local fallback candidates. `--runtime as2` records AS2/provider metadata and uses model-backed candidate generation only when a provider key is present in the process environment. Reports include `model_ready`, provider, base URL, and model name, but never persist API keys.

Run only a benchmark split:

```bash
.venv/bin/python backend/openclaw/benchmark.py --split holdout --repeats 3
```

`--split all` is the default. Tasks can declare `split: dev` or `split: holdout`; reports include split counts and per-split summaries so improvements can be checked on held-out tasks instead of only on the task families used while tuning.

Run a provider/model matrix:

```bash
.venv/bin/python backend/openclaw/model_matrix.py --config benchmarks/model_matrix.example.json --split holdout --repeats 1
```

The matrix runner executes the same benchmark protocol for each enabled config entry. Entries can require env vars such as `DEEPSEEK_API_KEY`, but the config must not contain the secret value. Reports include `required_env_present`, `missing_required_env`, provider/model metadata, model skip/fallback rates, and each entry's benchmark summary.

Latest no-key matrix smoke:

- Report: `data/model_matrix/20260622T031111Z/matrix_report.md`
- Metrics: `data/model_matrix/20260622T031111Z/matrix_metrics.json`
- Split: holdout
- Repeats: 1
- Entries: deterministic baseline, DeepSeek, OpenAI-compatible, DashScope
- Provider keys present: none

This smoke validates the matrix runner, AS2 package detection, missing-env reporting, and model skip/fallback accounting. It does not measure real model quality because no provider key was available in the process environment.

## Stop Criteria

Iteration stops when all of the following are true:

- At least 24 benchmark tasks.
- At least 3 repeats per strategy.
- At least 6 holdout tasks are included and evaluated.
- `audit_astar` improves success rate over `greedy_topk` by at least 25 percentage points.
- `audit_astar` improves mean score by at least 0.10.
- The same success-rate and mean-score improvements also hold on the holdout split.
- `audit_astar` has no safety/reliability regression: no higher invalid-tool, hallucinated-action, loop-failure, or unsafe-auto-allow counts.
- `audit_astar` mean latency is at most 2x `greedy_topk`.

## Metrics

| Metric | Meaning |
| --- | --- |
| success_rate | Fraction of tasks satisfying all task constraints. |
| mean_score | Soft score after penalties for missing expected behavior or unsafe behavior. |
| invalid_tool_call_count | Executed tool calls outside the known tool registry. |
| hallucinated_action_count | Selected/called tools outside the known tool registry. |
| loop_failure_count | Repeated reasoning action signatures. |
| unsafe_auto_allow_count | Forbidden tools that were automatically allowed. |
| permission_intervention_count | ask/deny permission outcomes. |
| search_event_count | Search trace density for optimized planners. |
| model_event_count | AS2/model runtime event density. |
| model_started_count | Number of benchmark runs that attempted a model call. |
| model_result_count | Number of model calls that produced usable candidates. |
| model_fallback_count | Number of model-started runs that fell back to deterministic candidates. |
| model_skipped_count | Number of runs where model generation was skipped, usually because no provider key was present. |
| model_success_rate | `model_result_count / model_started_count`. |
| model_fallback_rate | `model_fallback_count / model_started_count`. |
| model_skip_rate | `model_skipped_count / runs`. |
| latency_seconds | Wall-clock execution time. |
| split_summary | The same metrics grouped by `dev` and `holdout`. |

## Current Sample Task Families

- `workspace_grounding`: read-only grounding and audit completeness.
- `permission_trap`: risky actions must be surfaced and gated.
- `tool_path`: allowed edit/test paths must include file and command steps.
- `safety`: DONT_ASK must not silently mutate.
- `production_safety`: deployment must be treated as high-risk.

The current suite has 24 tasks across these families, split into 15 dev tasks and 9 holdout tasks. It is large enough for the current local deterministic stop protocol; the next expansion should add more repo-grounded tasks and model-backed repeated runs.

## Current Protocol Result

Latest run:

- Report: `data/benchmarks/20260618T091019Z/report.md`
- Metrics: `data/benchmarks/20260618T091019Z/metrics.json`
- Task count: 24, split into 15 dev tasks and 9 holdout tasks
- Repeats: 3
- Stop criteria met: true

| Strategy | Success rate | Mean score | Mean latency | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.3255s | 0 | 0 | 0 | 0 |
| `greedy_topk` | 20.83% | 0.7361 | 0.2833s | 0 | 0 | 0 | 0 |

The measured success delta is +79.17 percentage points, mean-score delta is +0.2639, and latency ratio is 1.1490x.

Holdout split:

| Strategy | Success rate | Mean score | Mean latency | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.3470s | 0 | 0 | 0 | 0 |
| `greedy_topk` | 33.33% | 0.7963 | 0.2823s | 0 | 0 | 0 | 0 |

Holdout success delta is +66.67 percentage points and holdout mean-score delta is +0.2037.
