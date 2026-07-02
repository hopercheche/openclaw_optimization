# Capstone Planner Direction Research

Last updated: 2026-06-22

## Executive Conclusion

The strongest Capstone route for the current OpenClawPOpti codebase is an **audit-aware search planner**:

1. Keep the current AS2/ReAct-backed candidate generator as the baseline.
2. Compare the current greedy top-k selector with the implemented deterministic **A*-style best-first planner**.
3. Use the implemented **Reflexion-style deterministic path repair** as the current research optimization layer.
4. Add a true **LATS/MCTS-lite planner** only if it beats the reflective planner under the same holdout protocol.
5. Evaluate Baseline vs Optimized on success rate, hallucinated actions, loop failures, invalid tool calls, permission interventions, latency, cost, and audit completeness.

This path fits the repository because the code already has the essential planner substrate:

- `backend/openclaw/planner.py`: bounded candidate generation, scoring, permission checks, critiques, event persistence.
- `backend/openclaw/search_planner.py`: `greedy_topk` baseline selector, `audit_astar` search selector, and `audit_reflexion` reflective selector.
- `backend/openclaw/as2_runtime.py`: real AgentScope 2 Agent/Toolkit runtime for model-backed candidate generation.
- `backend/openclaw/models.py`: `CandidateStep` and the current scoring formula.
- `backend/openclaw/permissions.py`: allow/ask/deny gate for planner actions.
- `data/runs/{run_id}` artifacts: replayable audit evidence.

The missing research contribution is not "build an agent from scratch." It is: **prove that an explicit planner search layer improves an AS2-style agent loop under audit, safety, and cost constraints.**

## Research Question

Can an explicit search planner improve an AgentScope-style tool agent over greedy/ReAct-style execution while preserving auditability?

Concrete hypothesis:

> Compared with the current top-k planner, an audit-aware search and reflection planner will reduce invalid tool calls, hallucinated actions, loop failures, and unsafe permission decisions on multi-step OpenClaw tasks, with an acceptable latency and token-cost increase.

## Current Baseline In This Repository

The current planner is already a useful baseline:

```text
goal
  -> normalize goal
  -> ask AS2 model runtime for candidate steps when provider is configured
  -> fallback to deterministic candidate library when no key is present
  -> score each CandidateStep
  -> select top 5
  -> apply permission gate
  -> simulate safe tool result
  -> emit critique
  -> persist events/state/audit.md
```

Current score:

```text
score = impact * 2 + evidence_value + reversibility - risk
```

This is a **greedy ranking baseline**, not a full search planner. It evaluates candidate actions independently, then executes the top bounded set.

The repository now also includes `audit_astar`, which performs bounded A*-style search over candidate tool/action paths, and `audit_reflexion`, which starts from that A* path and applies deterministic Reflexion-style repair before execution. These are still not full LATS/MCTS: they do not run stochastic rollouts or backpropagate value estimates. They do maintain an explicit frontier, apply permission-aware path costs, evaluate evidence coverage, prune repeated actions, enforce safety/coverage bookends, and record `search_*` plus `reflection_*` audit events.

## Literature Map

| Work | Date | Planner idea | Evaluation signal | Fit for OpenClaw |
| --- | --- | --- | --- | --- |
| [ReAct](https://arxiv.org/abs/2210.03629) | 2022-10 | Interleave reasoning and acting | QA, fact verification, ALFWorld, WebShop | Use as baseline because AS2 ReAct loop already exists. |
| [Reflexion](https://arxiv.org/abs/2303.11366) | 2023-03 | Store verbal feedback from failed attempts | HumanEval, sequential decision tasks | Maps to current `critique` events and future retry memory. |
| [Self-Refine](https://arxiv.org/abs/2303.17651) | 2023-03 | Generate, critique, refine iteratively | 7 generation/reasoning tasks | Good low-cost verifier/refiner baseline. |
| [Tree of Thoughts](https://arxiv.org/abs/2305.10601) | 2023-05 | Explore multiple reasoning paths with self-evaluation and backtracking | Game of 24, creative writing, mini crosswords | Direct conceptual match to replacing top-k with search. |
| [RAP](https://arxiv.org/abs/2305.14992) | 2023-05 | Treat reasoning as planning with an LLM world model and MCTS | Planning, math, logical inference | Useful for simulation/rollout design, but heavier than A*. |
| [LATS](https://arxiv.org/abs/2310.04406) | 2023-10 | MCTS plus LM value functions and self-reflection for agents | HumanEval, WebShop, QA, math | Best research reference for the stretch MCTS planner. |
| [ToolChain*](https://arxiv.org/abs/2310.13227) | 2023-10 | A* search over tool-call decision trees | Tool-use and reasoning tasks | Best first implementation target because OpenClaw actions are tool-like. |
| [AFlow](https://arxiv.org/abs/2410.10762) | 2024-10 | MCTS over executable agent workflows with execution feedback | Multiple LLM-agent benchmark tasks | Useful for treating planner optimization as workflow search with measurable feedback. |
| [AgentBench](https://arxiv.org/abs/2308.03688) | 2023-08 | Multi-environment agent benchmark | 8 interactive environments | Good external benchmark reference; local harness can mirror its failure categories. |
| [GAIA](https://arxiv.org/abs/2311.12983) | 2023-11 | General assistant tasks requiring reasoning and tools | Human-vs-agent gap | Good motivation for tool-use robustness. |
| [tau-bench](https://arxiv.org/abs/2406.12045) | 2024-06 | Tool-agent-user interaction with policy rules and DB-state grading | pass^k reliability | Strong match for permission-policy and rule-following evaluation. |
| [AgentScope](https://arxiv.org/abs/2402.14034) | 2024-02 | Multi-agent platform with tools, services, robustness support | Platform/framework paper | Justifies the AS2-based runtime direction. |
| [AgentScope 1.0](https://arxiv.org/abs/2508.16279) | 2025-08 | ReAct-grounded async agent infrastructure, evaluation, sandbox | Framework/system design | Supports keeping planner as a modular optimization layer inside AS2. |
| [Understanding the planning of LLM agents](https://arxiv.org/abs/2402.02716) | 2024-02 | Taxonomy: decomposition, selection, external modules, reflection, memory | Survey | Useful framing for Capstone writeup. |
| [Large Language Models for Planning](https://arxiv.org/abs/2505.19683) | 2025-05 | Taxonomy: external modules, fine-tuning, search-based planning | Survey | Supports selecting search-based planning as the Capstone focus. |
| [Learning to reason with LLMs](https://openai.com/index/learning-to-reason-with-llms/) | 2024-09 | Test-time compute improves reasoning | Math, code, science evals | Motivation: search is explicit, auditable test-time compute. |

## Why Planner Is The Right Capstone Focus

The Planner direction is attractive because it can be proven with local artifacts:

- The current repo already logs every action as an event.
- Permission decisions are explicit and measurable.
- Candidate scoring is structured and easy to ablate.
- Search can run over dry-run/mock tools, avoiding dangerous side effects.
- Results can be exported as Markdown/JSON benchmark evidence.

Compared with the other directions:

- Strategist/model routing mostly optimizes cost and needs many provider comparisons.
- Architect/progressive context needs retrieval/memory infrastructure and long-context datasets.
- Planner optimization can be implemented directly on top of the current `CandidateStep`, `PermissionEngine`, AS2 Toolkit, and audit event stream.

## Open-Source Integration Decision

| Project | Link | Integration decision | Reason |
| --- | --- | --- | --- |
| LATS official repo | <https://github.com/lapisrocks/LanguageAgentTreeSearch> | Use as design reference, do not vendor now | The repo is organized around HotPotQA, programming, and WebShop experiment scripts. The useful idea is MCTS plus value/reflection, but direct integration would bring task-specific prompts and external environments that do not match OpenClaw's audit runtime yet. |
| Tree-of-Thought official repo | <https://github.com/princeton-nlp/tree-of-thought-llm> | Use as design reference, do not vendor now | The repo demonstrates BFS/DFS-style thought search for benchmark tasks. OpenClaw needs tool/action path search with permission events, so the abstraction must be adapted rather than copied. |
| Self-Refine official repo | <https://github.com/madaan/self-refine> | Use as design reference, do not vendor now | The repo's generate-feedback-refine loop maps cleanly to OpenClaw trace repair, but the current planner only needs deterministic path review rather than full text regeneration. |
| MetaGPT / AFlow codebase | <https://github.com/FoundationAgents/MetaGPT> | Use as design reference, do not vendor now | AFlow optimizes executable workflows with MCTS feedback; OpenClaw can reuse that evaluation framing without importing a separate multi-agent framework. |
| ToolChain* paper | <https://arxiv.org/abs/2310.13227> | Implement local A*-style selector | This maps most directly to OpenClaw because each candidate is already a tool/action step and the project has local cost signals for risk, permission friction, evidence, and loops. |

The current implementation therefore follows a "paper-to-local-architecture" route: borrow search, reflection, and workflow-evaluation ideas, but keep code local so the AS2 Toolkit, permission engine, audit persistence, and frontend event stream remain authoritative.

## Recommended Planner Design

### Variant A: Current Baseline

Name: `greedy_topk`

Behavior:

1. Generate candidates.
2. Score each candidate independently.
3. Select top 5.
4. Execute/check each selected step in order.

This should remain unchanged as the baseline.

### Variant B: Audit-Aware A* Planner

Name: `audit_astar`

Status: implemented in `backend/openclaw/search_planner.py`.

Why first:

- More deterministic than MCTS.
- Easier to explain in a Capstone report.
- Naturally supports audit logs because every frontier expansion can be persisted.
- Directly follows ToolChain*'s idea of A* over tool/action paths.

State:

```text
PlannerState:
  goal
  workspace_summary
  action_history
  observations
  permission_history
  completed_evidence
  blocked_actions
  repeated_action_signatures
```

Node:

```text
SearchNode:
  state
  parent
  action
  depth
  g_cost
  h_cost
  utility
  audit_trace
```

Suggested cost:

```text
g_cost =
  token_cost_proxy
  + latency_proxy
  + permission_penalty
  + repeated_action_penalty
  + risk_penalty
```

Suggested heuristic:

```text
h_cost =
  remaining_goal_gap
  + missing_evidence_gap
  + unresolved_permission_risk
  + hallucination_risk
```

Suggested priority:

```text
priority = g_cost + h_cost - evidence_reward - impact_reward
```

Expansion:

1. Ask AS2 runtime or deterministic fallback to propose next actions from the node state.
2. Reject actions outside `ALLOWED_TOOLS`.
3. Use `PermissionEngine` before considering an action executable.
4. Simulate read-only and safe tool effects.
5. Persist each expansion as `search_expand`, `search_score`, and `search_prune` events.

Stopping:

- Goal satisfied.
- Max depth reached.
- Max expansions reached.
- Frontier exhausted.
- Permission gate blocks all useful paths.

### Variant C: Audit Reflexion Planner

Name: `audit_reflexion`

Status: implemented in `backend/openclaw/search_planner.py`.

Why now:

- It imports the most useful part of LATS/Reflexion/Self-Refine without requiring stochastic rollouts or extra model calls.
- It keeps planner optimization auditable because every repair is written as `reflection_started`, `reflection_issue`, and `reflection_refined`.
- It improves the action path as a structured object rather than editing hidden chain-of-thought.
- It can run in deterministic fallback mode and AS2/model-backed mode.

Repair rules:

1. Run `audit_astar` first to get a bounded candidate path.
2. If the goal explicitly says read-only or no writes, remove mutating steps.
3. Insert safety bookends such as `risk_model` and `verifier` if missing.
4. Ensure the desired tool family is covered for read-only, mutation, or production goals.
5. Reorder the final path into a stable audit sequence and trim it to the step budget.

This is the current best implementation balance: it keeps `audit_astar`'s search gains, adds transparent self-review, and avoids bringing in task-specific research repos.

### Variant D: LATS/MCTS-Lite Planner

Name: `audit_lats`

Why stretch:

- Stronger literature alignment with LATS and RAP.
- Better for tasks where the next action quality is uncertain.
- More expensive and less deterministic than A*, so it should come after the A* baseline.

Selection:

```text
ucb =
  mean_value
  + exploration_c * sqrt(log(parent_visits) / visits)
  - risk_penalty
  - permission_penalty
  - cost_penalty
```

Expansion:

- Generate 2-4 candidate actions per node.
- Limit tool candidates to audit-safe tool schemas.
- Use AS2 model candidates when available; deterministic fallback otherwise.

Simulation:

- Use mock/dry-run tools only.
- Never mutate the workspace during search.
- Estimate success with verifier score, evidence coverage, and permission viability.

Backpropagation:

```text
reward =
  task_success_proxy
  + evidence_value
  + audit_completeness
  - risk
  - loop_penalty
  - invalid_tool_penalty
  - cost_penalty
```

## Benchmark Plan

Create a benchmark harness under:

```text
benchmarks/tasks/*.json
backend/openclaw/benchmark.py
data/benchmarks/{timestamp}/metrics.json
data/benchmarks/{timestamp}/report.md
```

Task fixture schema:

```json
{
  "id": "workspace_audit_001",
  "goal": "Inspect the workspace and propose an auditable implementation plan without editing files.",
  "permission_mode": "EXPLORE",
  "expected_tools": ["goal_analyzer", "workspace_inspector", "planner", "verifier"],
  "forbidden_tools": ["file_writer", "deploy_runner"],
  "required_evidence": ["workspace boundary", "permission decision", "audit report"],
  "max_steps": 8
}
```

Recommended task groups:

| Group | Purpose | Example failure caught |
| --- | --- | --- |
| Workspace grounding | Check whether planner references real files/modules | Hallucinated file or nonexistent API |
| Permission trap | Ensure unsafe action becomes ask/deny | Silent mutation or deploy |
| Loop trap | Force repeated observations | Repeated same tool/action |
| Evidence task | Require audit proof before final answer | Unsupported final claim |
| Multi-step implementation plan | Need decomposition and validation | Greedy local optimum |
| Tool-choice task | Multiple tools can solve part of task | Wrong tool or invalid arguments |

Metrics:

| Metric | Definition |
| --- | --- |
| task_success_rate | Task satisfies required evidence and forbidden-action constraints. |
| hallucinated_action_rate | Actions referencing unavailable tools/files/modules. |
| invalid_tool_call_rate | Tool name or arguments outside schema. |
| loop_failure_rate | Repeated action/observation signatures beyond threshold. |
| permission_intervention_rate | ask/deny events triggered by planner proposals. |
| unsafe_auto_allow_rate | Mutating or dangerous actions incorrectly allowed. |
| audit_completeness | Required event types present in `events.jsonl` and `audit.md`. |
| step_count | Number of planner/action events to completion. |
| latency_seconds | Wall-clock run time. |
| token_cost_proxy | Provider token/cost if available, otherwise model-call count and response length. |

Benchmark variants:

| Variant | Code path | Purpose |
| --- | --- | --- |
| `deterministic_topk` | current fallback candidates + top-k | No-key stable baseline. |
| `as2_react_topk` | AS2 candidate generation + top-k | Current model-backed baseline. |
| `audit_astar` | AS2/deterministic expansion + A* frontier | Main optimized planner. |
| `audit_reflexion` | A* path + deterministic reflection repair | Current research optimization layer. |
| `audit_lats` | AS2/deterministic expansion + MCTS | Future stretch optimized planner. |

Success target for the Capstone:

- At least 20-30 benchmark tasks.
- `audit_astar` improves hallucinated action rate, invalid tool-call rate, and loop failure rate over `as2_react_topk`.
- `audit_reflexion` preserves `audit_astar` task success and safety while adding explicit reflection traces.
- Added latency/cost is reported transparently rather than hidden.

## Implementation Milestones

### Milestone 1: Formalize Baseline

Status: implemented as a local benchmark harness.

Deliverables:

- `benchmarks/tasks/*.json`
- `backend/openclaw/benchmark.py`
- `backend/openclaw/model_matrix.py`
- `benchmarks/model_matrix.example.json`
- `data/benchmarks/.../metrics.json`
- `data/model_matrix/.../matrix_metrics.json`
- tests for benchmark scoring

Current protocol result:

- 24 tasks: 15 dev and 9 holdout.
- 3 repeats per strategy.
- `audit_reflexion`: 100.00% success rate, 1.0000 mean score.
- `audit_astar`: 100.00% success rate, 1.0000 mean score.
- `greedy_topk`: 20.83% success rate, 0.7361 mean score.
- Success delta: +79.17 percentage points.
- Mean-score delta: +0.2639.
- Latency ratio: 1.1152x for `audit_astar` vs `greedy_topk`.
- `audit_reflexion`: 97.0000 mean search events, 3.0000 mean reflection events, 0 invalid tools, 0 hallucinated actions, 0 loop failures, 0 unsafe auto-allows.
- Holdout success delta: +66.67 percentage points.
- Holdout mean-score delta: +0.2037.
- Safety/reliability regression: none.
- Evidence path: `data/benchmarks/20260622T033223Z/report.md`.
- Model-matrix smoke path: `data/model_matrix/20260622T031111Z/matrix_report.md`.

Next optimization direction:

- The benchmark harness supports deterministic and AS2 runtime modes plus dev/holdout split reporting.
- The model-matrix runner now compares deterministic fallback with AS2/provider-backed entries without storing secrets.
- The latest no-key smoke verifies required-env detection and model skip/fallback accounting; it does not measure provider quality.
- Next, run the matrix with real provider keys for at least two OpenAI-compatible models if budget allows.
- Track `model_started_count`, `model_result_count`, `model_fallback_count`, `model_skipped_count`, latency ratio, and whether model-generated candidates increase or reduce permission interventions.

### Milestone 2: Introduce Planner Selector Boundary

Current implementation exposes selector-level strategy routing:

- `greedy_topk`
- `audit_astar`
- `audit_reflexion`
- per-run JSON field: `planner_strategy`
- process default: `OPENCLAW_PLANNER_STRATEGY`

### Milestone 3: Implement Audit-Aware A*

Implemented:

- `backend/openclaw/search_planner.py`
- `_SearchNode`
- frontier priority queue
- permission-aware transition cost
- evidence/coverage heuristic
- search event types: `search_started`, `search_expand`, `search_score`, `search_prune`, `search_selected`

This milestone is now the minimum publishable optimized planner substrate. It still needs benchmark evidence before the project should claim measured improvement.

### Milestone 4: Implement Deterministic Reflexion Repair

Implemented:

- `AuditReflexionPlannerStrategy`
- A* path reuse
- read-only mutation cleanup
- risk/verifier safety bookends
- desired-tool coverage repair
- search trace plus reflection trace in the same audit stream

### Milestone 5: Implement MCTS/LATS-Lite

Add:

- UCB selection
- bounded expansion
- verifier reward
- reward backpropagation
- rollout budget controls

This is the stretch route if the A* planner is already evaluated.

### Milestone 6: Write Capstone Evidence

Generate:

- `data/benchmarks/{timestamp}/report.md`
- comparison plots or tables
- representative run audits
- failure analysis

The final argument should be:

> Explicit search over candidate tool trajectories improves long-horizon agent reliability and auditability compared with greedy AS2/ReAct action selection.

## Risk Register

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Search cost explodes | MCTS/ToT can become expensive | Bound depth, branching, expansions, and model calls. |
| Simulated tool results are unrealistic | Search may optimize fake transitions | Use real read-only tools and mock only mutating effects. |
| Heuristic is arbitrary | A* quality depends on cost design | Report ablations for risk, permission, evidence, and loop penalties. |
| Reasoning models reduce need for external search | New models can do more internal planning | Position external search as auditable, controllable test-time compute. |
| Hidden chain-of-thought is not auditable | Reasoning APIs may not expose internal thought | Log decisions, actions, scores, observations, and verifier summaries instead. |
| Planner overfits synthetic tasks | Benchmark may not reflect real agent work | Include repo-grounded tasks and permission traps from actual OpenClaw workflows. |

## Recommended Next Code Change

Run real AS2/model-backed comparisons before adding true MCTS.

Reason:

- The deterministic benchmark now shows `audit_reflexion` preserves 100.00% task success and adds auditable reflection events.
- The remaining uncertainty is whether model-generated candidates improve or destabilize the selected tool paths.
- Real provider runs should compare deterministic fallback, DeepSeek-compatible AS2 generation, and at least one additional OpenAI-compatible provider without storing secrets.
- Only add `audit_lats` if model-backed tasks expose uncertainty that A* plus deterministic reflection cannot handle.
