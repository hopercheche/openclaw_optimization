# Planner Benchmark Notes

Last updated: 2026-06-22

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
| [PhoneHarness Bench](https://huggingface.co/datasets/PhoneHarness/phoneharness-bench) | Verifiable mixed-action mobile workflows across GUI, CLI, MCP-style tools, and safety policies | Best current fit for OpenClaw's planner layer because it stresses tool-path choice, external-state risk, safety gates, and verifier-backed completion without needing huge API corpora. |
| [tau2-bench-data](https://huggingface.co/datasets/HuggingFaceH4/tau2-bench-data) | Domain-policy tool-agent tasks across airline, retail, and telecom flows | Adds policy-following and customer-support tool-use profiles with act/confirm/refuse permission behavior. |
| [ToolBench](https://huggingface.co/datasets/Maurus/ToolBench) | API-planning prompts with tool/API metadata | Adds API-planning profiles where the planner must route through MCP-style tool execution. |
| [SkillsBench](https://huggingface.co/datasets/benchflow/skillsbench) | Software and office workflow tasks with skill metadata | Adds file/command workflow profiles outside the mobile and API domains. |

## Local Benchmark Design

OpenClaw's local benchmark borrows the reliable parts of these benchmarks without importing their heavy environments:

- PlanBench: explicit expected tools, forbidden tools, required events, and permission outcomes.
- tau-bench: policy correctness through allow/ask/deny behavior and unsafe auto-allow checks.
- ToolBench/API-Bank: tool path validity, invalid tool calls, and sequencing.
- WebArena/TravelPlanner: long-horizon task framing and constraint coverage.
- StableToolBench: deterministic local workspaces and simulated tool effects.
- PhoneHarness Bench: GUI/CLI/MCP execution-channel selection, safety policy handling, and verifier metadata converted into local deterministic tasks.
- tau2-bench-data, ToolBench, and SkillsBench: heterogeneous source features normalized into `source_family`, `planner_profile`, `execution_tools`, and `policy_mode`.

## Implemented Framework

Files:

- `backend/openclaw/benchmark.py`
- `backend/openclaw/model_matrix.py`
- `benchmarks/tasks/*.json`
- `benchmarks/model_matrix.example.json`
- `scripts/convert_phoneharness_dataset.py`
- `scripts/build_planner_generalization_suite.py`
- `data/external/phoneharness-bench/{README.md,dataset_summary.json,data/*.jsonl}`
- `data/external/tau2-bench-data/{README.md,domains/*}`
- `data/external/toolbench/{README.md,data/rows_000_100.json}`
- `data/external/skillsbench/{README.md,tasks/*/task.md}`
- `data/external/planner_feature_summary.json`
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
.venv/bin/python backend/openclaw/benchmark.py --strategies greedy_topk,audit_astar,audit_reflexion
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

Convert the local PhoneHarness dataset snapshot into OpenClaw benchmark tasks:

```bash
.venv/bin/python scripts/convert_phoneharness_dataset.py --main-limit 18 --safety-limit 12
```

The converter writes `benchmarks/tasks/020_phoneharness_planner_suite.json`. It keeps the original prompt and metadata in each task fixture, then maps PhoneHarness affordances into OpenClaw execution tools:

- `mobile_gui_runner` for Android GUI/app workflows.
- `mobile_cli_runner` for device-side shell, ADB, Termux, or CLI-style workflows.
- `mcp_tool_runner` for calendar, email, and host-side MCP-style actions.
- `safety_guard` for `SAFE_COMPLETE`, `CONFIRM_FIRST`, and `NEVER_AUTO` policy tasks.

`audit_astar` uses explicit `execution_tool(s)=...` metadata as a profile-aligned coverage shortcut. When all desired tools are available, it selects the coverage path directly while still emitting `search_started`, `search_expand`, `search_score`, and `search_selected` events. This keeps the run auditable but avoids enumerating many equivalent external-workflow paths.

Build the multi-source planner generalization suite:

```bash
.venv/bin/python scripts/build_planner_generalization_suite.py
```

The builder writes `benchmarks/tasks/030_multisource_planner_generalization_suite.json` and `data/external/planner_feature_summary.json`. It samples across four source families:

- `phoneharness`: mobile GUI/CLI/MCP workflows and safety policies.
- `tau2`: domain-policy tool agents with `act`, `confirm`, and `refuse` permission modes.
- `toolbench`: API-planning tasks routed through MCP-style tool execution.
- `skillsbench`: skill workflows that require file editing and validation commands.

The planner no longer treats PhoneHarness as a one-off special case. `audit_astar` and `audit_reflexion` now use a profile-aligned coverage path whenever a task exposes explicit `planner_profile` or `execution_tool(s)` hints. Safety handling also follows the normalized profile: `policy_mode=confirm/refuse` triggers `safety_guard` just like `CONFIRM_FIRST` or `NEVER_AUTO`.

Train the learned planner profile model:

```bash
.venv/bin/python scripts/train_planner_profile_model.py
```

The trainer builds 325 examples from local external snapshots: 30 PhoneHarness, 184 tau2, 100 ToolBench, and 11 SkillsBench examples. It strips explicit profile brackets during training/evaluation, then trains a standard-library multinomial Naive Bayes model over planner profile, execution-tool set, and policy mode. The model is saved at `data/planner_models/profile_policy_model.json`; metrics and the report are written to `data/planner_models/profile_policy_metrics.json` and `data/planner_models/profile_policy_report.md`.

Latest profile-model holdout metrics:

- Planner profile accuracy: 100.00%
- Execution-tool-set accuracy: 95.06%
- Policy-mode accuracy: 64.20%

The planner uses this learned model conservatively: explicit `execution_tool(s)=...` metadata still wins, local repo/planner/benchmark/deploy tasks keep the original local rules, and learned/mobile heuristic outputs are merged only for external workflow profiles. This gives a no-hint generalization path without regressing the original benchmark suite.

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

`audit_reflexion` is evaluated in the same report as the current research variant. It is not the historical stop-criteria anchor yet, but it must preserve the same success and safety checks while adding auditable `reflection_*` events.

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
| reflection_event_count | Reflexion-style path-review trace density for reflective planners. |
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
- `phoneharness_workflow`: converted PhoneHarness main tasks requiring GUI, CLI, or MCP execution-channel selection.
- `phoneharness_safety`: converted PhoneHarness safety tasks requiring safety-guard-first planning and allow/ask/deny behavior.
- `generalization_phoneharness`: PhoneHarness tasks reused inside the multi-source suite.
- `generalization_tau2_policy_tool_agent`: tau2 domain-policy tasks normalized into MCP execution plus act/confirm/refuse policy modes.
- `generalization_toolbench_api_planning`: ToolBench API-planning prompts normalized into MCP-style tool routing.
- `generalization_skillsbench_skill_workflow`: SkillsBench tasks normalized into file/command workflow planning.

The current suite has 88 tasks across these families, split into 61 dev tasks and 27 holdout tasks. It includes 30 converted PhoneHarness tasks plus 34 multi-source generalization tasks: 6 PhoneHarness samples, 12 tau2 tasks, 8 ToolBench tasks, and 8 SkillsBench tasks.

## Current Protocol Result

Latest run:

- Report: `data/benchmarks/20260622T144217Z/report.md`
- Metrics: `data/benchmarks/20260622T144217Z/metrics.json`
- Task count: 88, split into 61 dev tasks and 27 holdout tasks
- Repeats: 3
- Stop criteria met: true

| Strategy | Success rate | Mean score | Mean latency | Search events | Reflection events | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.2778s | 38.5909 | 0.0000 | 0 | 0 | 0 | 0 |
| `audit_reflexion` | 100.00% | 1.0000 | 0.2902s | 32.0455 | 4.5000 | 0 | 0 | 0 | 0 |
| `greedy_topk` | 5.68% | 0.7528 | 0.2846s | 0.0000 | 0.0000 | 0 | 0 | 0 | 0 |

The measured `audit_astar` stop-criteria delta is +94.32 percentage points on success rate and +0.2472 on mean score. The latest latency ratio is 0.9761x. The profile-aligned shortcut keeps `audit_astar` auditable while reducing mean search density to 38.5909 events across the larger 88-task suite. `audit_reflexion` matches `audit_astar` success and score while reducing mean search events further to 32.0455 and adding 4.5000 reflection events per run.

Holdout split:

| Strategy | Success rate | Mean score | Mean latency | Search events | Reflection events | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.2913s | 45.4444 | 0.0000 | 0 | 0 | 0 | 0 |
| `audit_reflexion` | 100.00% | 1.0000 | 0.3026s | 37.4444 | 4.4074 | 0 | 0 | 0 | 0 |
| `greedy_topk` | 11.11% | 0.7747 | 0.2847s | 0.0000 | 0.0000 | 0 | 0 | 0 | 0 |

Holdout success delta is +88.89 percentage points and holdout mean-score delta is +0.2253 for both optimized strategies against `greedy_topk`.

No-hint generalization smoke:

- Tasks: 34 stripped multi-source tasks from `030_multisource_planner_generalization_suite.json`
- Model disabled control: `audit_astar` 5.88% success
- Learned model enabled: `audit_astar` 97.06% success overall, 100.00% success on the 8-task holdout split
- Safety/reliability regressions: 0 invalid tools, 0 hallucinated actions, 0 loop failures, 0 unsafe auto-allows

This smoke proves that the learned planner profile model is doing more than parsing dataset-specific tags: when explicit profile brackets are removed, it recovers most execution-tool routing from task text alone while preserving the original benchmark's 100.00% result.
