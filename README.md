# OpenClawPOpti Midterm Contribution Report

This README is written as my individual contribution draft for the group midterm report. It focuses on the part I am responsible for: the Planner direction in the OpenClaw agent optimization project. The language is intentionally report-ready so it can be merged into the final group submission.

## 1. Output Goal

My goal is to build and validate an auditable planner layer for an AgentScope-style tool agent. The planner should improve multi-step task execution by choosing safer and more goal-aligned tool/action paths than a simple greedy baseline.

The expected output is not only a conceptual design. It should be a runnable prototype with API endpoints, event traces, permission decisions, benchmark tasks, evaluation reports, and enough evidence for the team to explain what has been implemented by the midterm checkpoint.

The core research question for my part is:

> Can an explicit planner search layer improve an agent's tool selection, permission handling, and task success rate while keeping every decision auditable?

## 2. Technical Architecture and Solution Plan

The current Planner track is implemented as an audit-first runtime around AgentScope 2 concepts. The system keeps the public frontend/backend boundary simple, while isolating model-backed AgentScope execution behind an adapter layer.

```text
Frontend static console
  -> OpenClaw REST/SSE API
  -> RunManager session
  -> LocalAuditPlanner control plane
  -> optional AgentScope 2 runtime boundary
  -> OpenClaw permission gate
  -> persisted events.jsonl, state.json, and audit.md
```

The main backend modules are:

| Area | Files | Purpose |
| --- | --- | --- |
| API and run management | `backend/openclaw/server.py` | Exposes health, run creation, run lookup, event, stream, and audit endpoints. |
| Planner control plane | `backend/openclaw/planner.py` | Generates candidate steps, selects a planner path, applies permissions, simulates safe tool execution, and writes final output. |
| Search planner | `backend/openclaw/search_planner.py` | Implements `greedy_topk`, `audit_astar`, and `audit_reflexion`. |
| Permission gate | `backend/openclaw/permissions.py` | Maps each action into `allow`, `ask`, or `deny` behavior under the current permission mode. |
| Audit persistence | `backend/openclaw/storage.py`, `backend/openclaw/audit.py` | Stores run state, event logs, and Markdown audit reports. |
| AgentScope integration | `backend/openclaw/as2_adapter.py`, `backend/openclaw/as2_runtime.py`, `backend/openclaw/as2_openai.py` | Detects AgentScope, builds the optional model-backed runtime, and falls back to deterministic candidates when credentials are unavailable. |
| Benchmarking | `backend/openclaw/benchmark.py`, `backend/openclaw/model_matrix.py` | Evaluates planner strategies and provider/model configurations. |
| Learned planner hint | `backend/openclaw/planner_profile_model.py`, `scripts/train_planner_profile_model.py` | Trains a lightweight Naive Bayes profile model for no-hint routing of workflow/tool profiles. |

The baseline strategy is `greedy_topk`, which independently ranks candidate actions and chooses the highest-scoring steps. The optimized strategies are:

- `audit_astar`: a bounded A*-style planner that searches over candidate tool/action paths. It scores paths using impact, evidence value, reversibility, risk, permission friction, repeated actions, and missing required tools.
- `audit_reflexion`: a reflective variant that starts from the A* path and applies deterministic review/repair steps. It adds `reflection_*` events so the revision process is also visible in the audit trail.

The architecture intentionally keeps OpenClaw in charge of permission checks and evidence logging. Even when a model-backed AgentScope runtime is available, the model proposes candidates, while OpenClaw enforces the execution boundary.

## 3. Current Outputs and Progress

By the midterm checkpoint, my part has the following working outputs:

- A runnable backend planner service with REST and SSE endpoints.
- A static frontend console under `frontend/` for creating runs, viewing live events, and reading audit reports.
- A local permission engine that classifies actions as `allow`, `ask`, or `deny`.
- Three planner strategies: `greedy_topk`, `audit_astar`, and `audit_reflexion`.
- AgentScope 2 integration boundaries with deterministic fallback when provider credentials are not configured.
- A benchmark harness with dev and holdout splits.
- Converted and normalized planner task suites from PhoneHarness, tau2-bench-data, ToolBench, and SkillsBench.
- A lightweight planner profile model trained from local multi-source fixtures.
- Persisted benchmark reports, JSON metrics, and per-run audit artifacts.

The latest deterministic benchmark uses 88 tasks, including 61 dev tasks and 27 holdout tasks, with 3 repeats per strategy. It compares the greedy baseline against the optimized planner strategies.

| Strategy | Success rate | Mean score | Mean latency | Search events | Reflection events | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.2778s | 38.5909 | 0.0000 | 0 | 0 | 0 | 0 |
| `audit_reflexion` | 100.00% | 1.0000 | 0.2902s | 32.0455 | 4.5000 | 0 | 0 | 0 | 0 |
| `greedy_topk` | 5.68% | 0.7528 | 0.2846s | 0.0000 | 0.0000 | 0 | 0 | 0 | 0 |

On the holdout split, both optimized strategies reached 100.00% success, while `greedy_topk` reached 11.11%. This suggests that explicit planning improves the benchmark outcomes without introducing safety regressions in the local deterministic setting.

The planner profile model also provides initial no-hint generalization evidence. It was trained on 325 local examples from PhoneHarness, tau2, ToolBench, and SkillsBench. Its holdout accuracy is 100.00% for planner profile prediction, 95.06% for execution-tool prediction, and 64.20% for policy-mode prediction.

## 4. Evidence of Current Outputs

The current evidence is stored directly in the repository:

| Evidence type | Location |
| --- | --- |
| Planner runtime code | `backend/openclaw/planner.py` |
| Planner search algorithms | `backend/openclaw/search_planner.py` |
| Permission gate | `backend/openclaw/permissions.py` |
| AgentScope 2 adapter/runtime | `backend/openclaw/as2_adapter.py`, `backend/openclaw/as2_runtime.py` |
| Benchmark runner | `backend/openclaw/benchmark.py` |
| Benchmark task suites | `benchmarks/tasks/*.json` |
| Latest benchmark report | `data/benchmarks/20260622T144217Z/report.md` |
| Latest benchmark metrics | `data/benchmarks/20260622T144217Z/metrics.json` |
| Per-run audit examples | `data/benchmarks/20260622T144217Z/artifacts/**/audit.md` |
| Planner profile model | `data/planner_models/profile_policy_model.json` |
| Planner profile model report | `data/planner_models/profile_policy_report.md` |
| Architecture notes | `docs/AS2_ARCHITECTURE.md` |
| Benchmark design notes | `docs/PLANNER_BENCHMARKS.md` |
| MVP plan | `docs/MVP_PLAN.md` |

Useful reproduction commands:

```bash
python -m unittest discover -s tests
python backend/openclaw/benchmark.py --repeats 3
python backend/openclaw/benchmark.py --split holdout --repeats 3
OPENCLAW_PLANNER_STRATEGY=audit_reflexion scripts/start_backend.sh
```

No final UI screenshots are committed yet. Before the group report is submitted, I can capture screenshots of the frontend console, event timeline, and generated `audit.md` page as visual evidence.

## 5. Risks, Challenges, and Limitations

The main limitation is that the strongest evidence currently comes from deterministic local benchmarks. The AgentScope 2 model-backed path exists, but real provider-quality comparisons still require stable API keys and repeated evaluation under the same benchmark protocol.

The second limitation is that `audit_astar` is a bounded A*-style search, not a full LATS or MCTS planner. It is intentionally simpler and easier to audit, but it does not yet include full rollout simulation or backpropagation.

The third risk is benchmark coverage. The current suite covers workspace grounding, permission traps, safety, deployment risk, mobile/CLI/MCP-style workflows, policy-tool-agent tasks, API planning tasks, and skill workflows. However, final evaluation should include more repo-grounded multi-step tasks that resemble realistic OpenClaw usage.

The fourth limitation is scope. My work focuses on the Planner direction. The broader capstone may also include Strategist and Architect directions, but those need to be integrated carefully so the final system does not become a collection of disconnected demos.

## 6. Plan and Goal for the Final Submission

For the final project, my plan is to strengthen the Planner contribution in four ways:

1. Run model-backed AS2/provider benchmarks with real credentials and compare them against the deterministic fallback.
2. Expand benchmark tasks with more realistic OpenClaw workflows, especially repo-grounded editing, validation, and deployment-safety scenarios.
3. Improve the reflective planner only if it beats or matches `audit_astar` under the same holdout protocol.
4. Add final report evidence, including frontend screenshots, benchmark tables, generated audit reports, and a concise architecture diagram.

My target final deliverable is a planner module that the team can present as a measurable optimization layer: baseline vs optimized planner, clear architecture, reproducible benchmark protocol, and auditable run artifacts.

## 7. My Role and Contribution in the Team

My team responsibility is the Planner direction. My contribution is to turn the planner idea into a working prototype and evidence package.

Specifically, I contributed:

- Designed the audit-first planner architecture.
- Implemented the backend planner runtime and API flow.
- Implemented baseline and optimized planner strategies.
- Integrated the AgentScope 2 runtime boundary.
- Built the permission gate and audit logging path.
- Built benchmark tasks, evaluation metrics, and report generation.
- Converted external planner/workflow datasets into local OpenClaw benchmark fixtures.
- Trained and evaluated the lightweight planner profile model.
- Wrote technical documentation for architecture, benchmark design, and project progress.

## 8. AI Usage Statement

I used AI coding assistants, including ChatGPT/Codex, to help with implementation planning, code drafting, debugging, documentation, and summarizing benchmark evidence. AI was used as an assistant for generating and refining code, organizing report language, and checking that the written explanation matched the repository artifacts.

I reviewed the generated code and documentation, selected the final technical direction, ran or inspected the benchmark evidence, and kept the final implementation grounded in the actual project files. No secret keys were provided to AI tools, and API credentials are expected to remain in local environment variables rather than committed files.
