# OpenClawPOpti

OpenClawPOpti contains Capstone work for OpenClaw agent optimization. The repository currently has two implemented tracks:

- Direction 1, The Strategist: a rule-based model router that routes requests to small / mid / large model tiers.
- Direction 2, The Architect: a local SQLite context index that archives completed run context and injects source-backed snippets into later planner runs.
- Direction 3, The Planner: an audit-first AgentScope 2 planner runtime with `greedy_topk`, `audit_astar`, and `audit_reflexion` planner strategies plus benchmark evidence.

It does not yet prove all three Capstone directions end to end. Direction 2 now has a retrieval/injection prototype, but it still needs broader benchmark evidence and model-backed AS2 prompt integration.

## Current Fit Against The Capstone

| Capstone requirement | Current status | Evidence in this repo |
| --- | --- | --- |
| Baseline OpenClaw Agent | Partial | The deterministic fallback planner provides a stable baseline loop with fixed candidate generation, scoring, permission checks, and audit logs. |
| Optimized OpenClaw Agent | Partial | The AS2-backed path embeds `Agent`, `OpenAIChatModel`, `Toolkit`, `AgentState`, `PermissionContext`, and `ReActConfig`; model-backed candidate generation is available when provider credentials are configured. |
| Direction 1: model routing | Implemented | `src/router/rule_based.py`, `src/pipeline/inference.py`, `src/evaluation/metrics.py`, `demo.py`, and `tests/test_mvp.py`. |
| Direction 2: progressive context | Prototype implemented | `backend/openclaw/context_index.py` archives completed run context into SQLite FTS, retrieves prior snippets at run start, and records `context_retrieval`, `context_injection`, and `context_archived` audit events. |
| Direction 3: search planner | Partially implemented | `audit_astar` performs bounded A*-style search; `audit_reflexion` adds deterministic reflection repair inspired by LATS, Reflexion, Self-Refine, ToolChain*, ToT, and AFlow. Full MCTS rollout/backpropagation remains a later extension. |
| Head-to-head proof | Partially implemented | Planner benchmark reports compare `greedy_topk`, `audit_astar`, and `audit_reflexion` on 88 tasks with dev/holdout splits, including converted PhoneHarness tasks plus a multi-source generalization suite from PhoneHarness, tau2-bench-data, ToolBench, and SkillsBench. The model-matrix runner can compare deterministic fallback with AS2/provider-backed runs, but real model evidence still requires provider keys at runtime. |

## Strategist Router

The Strategist router routes user requests to a model tier before inference.

```text
user input -> rule-based router -> small/mid/large model tier -> provider -> output + metrics
```

Modules:

| Module | Path | Purpose |
| --- | --- | --- |
| Model interface | `src/models/` | OpenAI-compatible provider and mock provider. |
| Rule-based router | `src/router/rule_based.py` | Keyword, length, and complexity heuristics. |
| Inference pipeline | `src/pipeline/inference.py` | Route, call provider, and return result. |
| Evaluation metrics | `src/evaluation/metrics.py` | Cost, latency, and tier distribution. |
| API service | `src/api/server.py` | FastAPI REST endpoints. |
| CLI demo | `demo.py` | Offline demo and benchmark entrypoint. |

Run the offline mock demo:

```bash
python3 demo.py demo
python3 demo.py query "请解释为什么梯度下降能够收敛"
python3 demo.py benchmark --file data/sample_queries.txt -o report.json
```

Start the router API:

```bash
python3 run_server.py
```

API endpoints:

- `GET /health`
- `POST /query`
- `POST /route`
- `POST /benchmark`

The router thresholds and model tiers live in `config/models.yaml`.

## Planner Runtime

The Planner track is an auditable AgentScope 2 runtime with local permission gates and persisted run evidence.

```text
frontend static console
  -> OpenClaw REST/SSE API
  -> RunManager session
  -> LocalAuditPlanner control plane
  -> AgentScope 2 runtime boundary
  -> OpenClaw permission gate
  -> events.jsonl/state.json/audit.md
```

Planner strategies:

- `greedy_topk`: baseline selector that ranks candidates independently by score.
- `audit_astar`: optimized selector inspired by ToolChain*, Tree of Thoughts, and LATS. It searches candidate tool/action paths with explicit costs for risk, permission friction, repeated actions, and missing evidence, then records `search_*` events before execution.
- `audit_reflexion`: reflective selector that starts from the A* path, then applies deterministic safety bookends, desired-tool coverage repair, explicit read-only cleanup, and `reflection_*` audit events.

Enable `audit_reflexion` for backend runs:

```bash
OPENCLAW_PLANNER_STRATEGY=audit_reflexion scripts/start_backend.sh
```

Or pass it per run:

```json
{"goal":"Plan an auditable workspace automation","permission_mode":"DEFAULT","planner_strategy":"audit_reflexion"}
```

## Planner Benchmarks

Run the deterministic benchmark:

```bash
.venv/bin/python backend/openclaw/benchmark.py --repeats 3
```

Run the same protocol through detected AS2/model-backed candidate generation when provider credentials are configured:

```bash
.venv/bin/python backend/openclaw/benchmark.py --runtime as2 --repeats 3
```

Run only the held-out split:

```bash
.venv/bin/python backend/openclaw/benchmark.py --split holdout --repeats 3
```

Run the provider/model matrix without storing secrets:

```bash
.venv/bin/python backend/openclaw/model_matrix.py --config benchmarks/model_matrix.example.json --split holdout --repeats 1
```

The matrix config stores only non-secret model metadata and names of required env vars. API keys are read from the process environment at runtime and are never written to reports.

Regenerate the converted PhoneHarness task suite:

```bash
.venv/bin/python scripts/convert_phoneharness_dataset.py --main-limit 18 --safety-limit 12
```

Build the multi-source planner generalization suite from the downloaded planner datasets:

```bash
.venv/bin/python scripts/build_planner_generalization_suite.py
```

That suite normalizes PhoneHarness, tau2-bench-data, ToolBench, and SkillsBench into shared planner features: `source_family`, `planner_profile`, `execution_tools`, and `policy_mode`.

Train the lightweight planner profile model from the downloaded datasets:

```bash
.venv/bin/python scripts/train_planner_profile_model.py
```

The trained model is saved to `data/planner_models/profile_policy_model.json`; its report is `data/planner_models/profile_policy_report.md`. It learns planner profile, execution-tool set, and policy mode from PhoneHarness, tau2-bench-data, ToolBench, and SkillsBench, then acts as a conservative hint when a new task has no explicit `execution_tool(s)=...` metadata.

Latest planner benchmark evidence:

```text
data/benchmarks/20260622T144217Z/report.md
data/benchmarks/20260622T144217Z/metrics.json
```

The latest run used 88 tasks with 3 repeats and met the stop criteria: `audit_astar` and `audit_reflexion` both reached 100.00% success rate vs `greedy_topk` at 5.68%. The profile-aligned shortcut and learned profile model preserve audit events: `audit_astar` recorded 38.5909 mean search events, and `audit_reflexion` recorded 32.0455 mean search events plus 4.5000 mean reflection events, with 0 invalid tools, hallucinated actions, loop failures, or unsafe auto-allows. On holdout, both optimized strategies reached 100.00% success rate vs `greedy_topk` at 11.11%.

No-hint generalization smoke:

```text
/tmp/openclaw_stripped_with_model/metrics.json
```

This smoke strips explicit profile metadata from the 34-task multi-source generalization suite. With the trained profile model enabled, `audit_astar` reached 97.06% overall success and 100.00% holdout success; with the model disabled, the same stripped suite reached 5.88% in the earlier control run.

Latest model-matrix smoke evidence:

```text
data/model_matrix/20260622T031111Z/matrix_report.md
data/model_matrix/20260622T031111Z/matrix_metrics.json
```

That smoke used the holdout split with no provider keys in the environment. It verifies matrix execution, required-env detection, and model skip/fallback accounting; it is not a real provider quality comparison.

See `docs/PLANNER_BENCHMARKS.md` and `docs/CAPSTONE_PLANNER_RESEARCH.md` for benchmark design and research notes.

## AS2 Model Provider

DeepSeek OpenAI-compatible runtime:

```bash
DEEPSEEK_API_KEY=... scripts/start_backend.sh
```

For local development, `scripts/start_backend.sh` automatically loads `.env.local` when present. `.env.local` is ignored by git and should contain secrets only on the local machine.

Optional model override:

```bash
OPENCLAW_DEEPSEEK_MODEL=deepseek-v4-pro DEEPSEEK_API_KEY=... scripts/start_backend.sh
```

Default DeepSeek settings:

```text
DEEPSEEK_BASE_URL=https://api.deepseek.com
OPENCLAW_DEEPSEEK_MODEL=deepseek-v4-flash
OPENCLAW_MODEL_TIMEOUT_SECONDS=45
```

Generic OpenAI-compatible runtime:

```bash
OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENCLAW_OPENAI_MODEL=... scripts/start_backend.sh
```

Do not commit API keys. The backend records only provider readiness, base URL, and model name in audit events.

## Planner API

- `GET /api/health`
- `GET /api/as2/architecture`
- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/stream`
- `GET /api/runs/{run_id}/audit.md`

Example:

```bash
curl -s http://127.0.0.1:8787/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"goal":"Plan an auditable workspace automation","permission_mode":"DEFAULT"}'
```

## Project Layout

```text
backend/openclaw/             # AS2 planner runtime and benchmark harness
benchmarks/                   # Planner benchmark tasks and model matrix config
config/models.yaml            # Strategist router model tiers and thresholds
data/                         # Sample router queries and committed benchmark evidence
docs/                         # AS2 architecture and planner benchmark notes
frontend/                     # Static planner console
scripts/                      # Planner backend/frontend launchers
src/                          # Strategist router
tests/                        # Planner and router tests
demo.py                       # Strategist CLI demo
run_server.py                 # Strategist API server
```

## Tests

Planner / AS2 tests:

```bash
.venv/bin/python -m unittest discover -s tests
```

Strategist router test:

```bash
python3 -m pytest tests/test_mvp.py
```

## Roadmap

1. Run the model matrix with real provider keys and compare model-backed candidate generation against deterministic fallback.
2. Extend planner benchmark tasks with more repo-grounded and model-backed cases.
3. Add true LATS/MCTS rollout and backpropagation only if it improves over `audit_reflexion` under the same holdout protocol.
4. Extend progressive context injection with AS2 prompt support, semantic retrieval, and compaction-vs-index benchmarks.
5. Strengthen Strategist routing with feature-based, cost-aware, or cascade routing.
