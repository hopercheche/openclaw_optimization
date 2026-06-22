# OpenClawPOpti

OpenClawPOpti contains Capstone work for OpenClaw agent optimization. The repository currently has two implemented tracks:

- Direction 1, The Strategist: a rule-based model router that routes requests to small / mid / large model tiers.
- Direction 3, The Planner: an audit-first AgentScope 2 planner runtime with `greedy_topk`, `audit_astar`, and `audit_reflexion` planner strategies plus benchmark evidence.

It does not yet prove all three Capstone directions end to end. Direction 2, The Architect, is still only represented by context-boundary plumbing in the planner runtime.

## Current Fit Against The Capstone

| Capstone requirement | Current status | Evidence in this repo |
| --- | --- | --- |
| Baseline OpenClaw Agent | Partial | The deterministic fallback planner provides a stable baseline loop with fixed candidate generation, scoring, permission checks, and audit logs. |
| Optimized OpenClaw Agent | Partial | The AS2-backed path embeds `Agent`, `OpenAIChatModel`, `Toolkit`, `AgentState`, `PermissionContext`, and `ReActConfig`; model-backed candidate generation is available when provider credentials are configured. |
| Direction 1: model routing | Implemented | `src/router/rule_based.py`, `src/pipeline/inference.py`, `src/evaluation/metrics.py`, `demo.py`, and `tests/test_mvp.py`. |
| Direction 2: progressive context | Partially implemented boundary | The planner runtime has workspace-scoped tools and audit-safe context boundaries, but no retrieval, memory block, or compaction benchmark yet. |
| Direction 3: search planner | Partially implemented | `audit_astar` performs bounded A*-style search; `audit_reflexion` adds deterministic reflection repair inspired by LATS, Reflexion, Self-Refine, ToolChain*, ToT, and AFlow. Full MCTS rollout/backpropagation remains a later extension. |
| Head-to-head proof | Partially implemented | Planner benchmark reports compare `greedy_topk`, `audit_astar`, and `audit_reflexion` on 24 tasks with dev/holdout splits. The model-matrix runner can compare deterministic fallback with AS2/provider-backed runs, but real model evidence still requires provider keys at runtime. |

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

Latest planner benchmark evidence:

```text
data/benchmarks/20260622T033223Z/report.md
data/benchmarks/20260622T033223Z/metrics.json
```

The latest run used 24 tasks with 3 repeats and met the stop criteria: `audit_reflexion` and `audit_astar` both reached 100.00% success rate vs `greedy_topk` at 20.83%. `audit_reflexion` recorded 3.0000 mean reflection events, 97.0000 mean search events, and 0 invalid tools, hallucinated actions, loop failures, or unsafe auto-allows. On holdout, `audit_reflexion` reached 100.00% success rate vs `greedy_topk` at 33.33%.

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
4. Add progressive context injection using memory blocks, retrieval, and compaction.
5. Strengthen Strategist routing with feature-based, cost-aware, or cascade routing.
