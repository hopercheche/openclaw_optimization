# OpenClawPOpti

OpenClawPOpti is an audit-first AgentScope 2 planner implementation for the OpenClaw Agent Optimization Capstone. The current code embeds a real AgentScope 2 Agent/Toolkit runtime, exposes an auditable planner loop, and records every run as replayable evidence.

The attached Capstone brief defines three optimization frontiers:

- Direction 1, The Strategist: route each subtask to the cheapest model that is still good enough.
- Direction 2, The Architect: inject context just in time instead of loading everything into one prompt.
- Direction 3, The Planner: replace greedy one-step execution with heuristic search planning such as MCTS or A*.

## Current Fit Against The Capstone

This repository contains part of the Capstone implementation. It does not yet satisfy the full three-direction requirement end to end.

| Capstone requirement | Current status | Evidence in this repo |
| --- | --- | --- |
| Baseline OpenClaw Agent | Partial | The deterministic fallback planner provides a stable baseline loop with fixed candidate generation, scoring, permission checks, and audit logs. |
| Optimized OpenClaw Agent | Partial | The AS2-backed path embeds `Agent`, `OpenAIChatModel`, `Toolkit`, `AgentState`, `PermissionContext`, and `ReActConfig`; model-backed candidate generation is available when provider credentials are configured. |
| Direction 1: model routing | Not implemented yet | Provider selection is centralized in `as2_adapter.py`, so a RouteLLM/FrugalGPT-style router can be added, but no router or cost benchmark exists yet. |
| Direction 2: progressive context | Partially implemented boundary | The runtime has workspace-scoped tools and audit-safe context boundaries, but it does not yet implement memory blocks, retrieval, compaction, or a just-in-time context benchmark. |
| Direction 3: search planner | Partially implemented | The planner already generates multiple candidate actions, scores them, prunes to top steps, applies permission gates, and records verifier critiques. Full MCTS/A* search is the next optimization step. |
| Head-to-head mathematical proof | Not implemented yet | Unit tests verify runtime/API behavior; benchmark tasks and metric aggregation still need to be added. |
| Modular OpenClaw upgrade | Partially implemented | Frontend/backend are decoupled, AS2 is behind an adapter/runtime layer, and every run persists `state.json`, `events.jsonl`, and `audit.md`. |

In short: the architecture is suitable for continuing the Capstone implementation, especially if the selected focus is The Planner. It is not yet a complete proof that all three frontiers improve over a baseline.

## What Is Implemented

- Runs an auditable planner on top of a real AgentScope 2 Agent/Toolkit runtime when provider credentials are configured.
- Falls back to a deterministic local planner when no model key is present, so every run still completes and produces evidence.
- Streams planner events to the frontend over Server-Sent Events.
- Persists every run under `data/runs/{run_id}`.
- Generates an `audit.md` report for every run.
- Serves a static frontend from `frontend/` that talks to the backend API.
- Uses `agentscope==2.0.1` for Agent, ReAct loop, Toolkit, permission context, `UserMsg` snapshots, and event type mapping.

## Architecture

```text
frontend static console
  -> OpenClaw REST/SSE API
  -> RunManager session
  -> LocalAuditPlanner control plane
  -> AgentScope 2 runtime boundary
       - Agent
       - OpenAIChatModel with OpenAICredential
       - Toolkit
       - AgentState session id
       - PermissionContext workspace scope
       - ReActConfig
       - streamed AgentScope events
  -> OpenClaw permission gate
  -> events.jsonl/state.json/audit.md
```

The model-backed AS2 path proposes candidate steps, but OpenClaw still owns permission enforcement and audit persistence. This keeps the system auditable even when the model provider changes.

## Planner Loop

The current planner is a bounded, auditable approximation of the Direction 3 goal:

1. Normalize the user goal.
2. Generate multiple candidate actions.
3. Score candidates by impact, evidence value, reversibility, and risk.
4. Select the top bounded path.
5. For each selected step, emit reasoning, permission, tool call, tool result, and critique events.
6. Produce a final response and Markdown audit report.

This is not full LATS/MCTS or ToolChain*/A* yet. The next planner milestone is to replace the fixed top-k selection with a real search tree:

- State: goal, workspace summary, action history, observations, permission state.
- Action: tool call or planning step.
- Value: expected task success, evidence value, loop risk, hallucination risk, and cost.
- Search: MCTS for exploration/exploitation or A* with `g+h` cost.

## AgentScope 2 Runtime

OpenClaw maps AgentScope 2 concepts to local modules:

- AS2 package and provider detection: `backend/openclaw/as2_adapter.py`
- Embedded AS2 Agent/Toolkit runtime: `backend/openclaw/as2_runtime.py`
- Planner orchestration: `backend/openclaw/planner.py`
- Permission policy: `backend/openclaw/permissions.py`
- Run persistence: `backend/openclaw/storage.py`
- Audit rendering: `backend/openclaw/audit.py`
- REST/SSE service: `backend/openclaw/server.py`

The embedded runtime registers four read-only OpenClaw tools:

- `openclaw_audit_schema`
- `openclaw_workspace_inventory`
- `openclaw_permission_probe`
- `openclaw_score_candidate`

The optional `agentscope.app` FastAPI service stack is detected but not required by the current implementation. The backend uses a lightweight Python standard-library HTTP service so the project runs without Node/npm or extra app-server infrastructure.

## Evaluation Plan

The Capstone requires a Baseline vs Optimized comparison. This repo should add a benchmark harness before claiming final optimization results.

Recommended metrics from the brief:

- Token or dollar cost.
- Task accuracy or success rate.
- Hallucination rate.
- Loop failure rate.
- Latency.
- Permission-gate interventions.

Suggested comparison:

| Variant | Description | Main metric |
| --- | --- | --- |
| Baseline | Single model, full context, greedy one-step planner | Current cost, accuracy, hallucination, loop failures |
| Optimized Planner | AS2 runtime plus MCTS/A* planner | Lower hallucination and loop failure rate |
| Optimized Strategist | RouteLLM/FrugalGPT-style model router | 60-80% lower model cost at similar accuracy |
| Optimized Architect | Letta/ACE-style progressive context injection | 20%+ improvement on complex context-heavy tasks |

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Run Locally

Start the backend:

```bash
scripts/start_backend.sh
```

Start the frontend in another terminal:

```bash
scripts/start_frontend.sh
```

Open:

```text
http://127.0.0.1:4173
```

## Model Provider

To enable the model-backed AS2 planner with DeepSeek's OpenAI-compatible API, provide a DeepSeek key at process start:

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

The same runtime also supports OpenAI-compatible OpenAI envs:

```bash
OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENCLAW_OPENAI_MODEL=... scripts/start_backend.sh
```

Do not commit API keys. The backend records only provider readiness, base URL, and model name in audit events.

## API

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

## Permission Modes

- `DEFAULT`: read-only actions are allowed; mutating actions ask.
- `EXPLORE`: read-only planning only; mutating actions deny.
- `ACCEPT_EDITS`: bounded workspace edits are allowed.
- `DONT_ASK`: uncertain or mutating actions deny.
- `BYPASS`: non-denied mutating actions are allowed in the sandboxed current implementation.

## Project Layout

```text
backend/openclaw/
  as2_adapter.py
  as2_runtime.py
  as2_openai.py
  audit.py
  models.py
  permissions.py
  planner.py
  server.py
  storage.py
docs/
  AS2_ARCHITECTURE.md
frontend/
  app.js
  index.html
  styles.css
scripts/
  start_backend.sh
  start_frontend.sh
tests/
  test_as2_adapter.py
  test_as2_runtime.py
  test_permissions.py
  test_planner.py
  test_server.py
```

## Test

```bash
.venv/bin/python -m unittest discover -s tests
```

## Roadmap To Full Capstone

1. Add a benchmark harness with shared task fixtures, metric aggregation, and Baseline vs Optimized reports.
2. Implement a real MCTS or A* planner module and compare it against the current greedy/top-k planner.
3. Add a model-routing layer inspired by RouteLLM or FrugalGPT.
4. Add progressive context injection using memory blocks, retrieval, and compaction.
5. Publish head-to-head results as Markdown/JSON artifacts under an audit or benchmark output directory.
