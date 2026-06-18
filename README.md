# OpenClawPOpti

Audit-first AgentScope 2 style planner MVP with a decoupled backend and frontend.

## What This MVP Does

- Runs an auditable planner on top of a real AgentScope 2 Agent/Toolkit runtime when provider credentials are configured.
- Streams planner events over SSE.
- Persists every run under `data/runs/{run_id}`.
- Generates an `audit.md` report for every run.
- Serves a static frontend from `frontend/` that talks to the backend API.
- Uses the real `agentscope==2.0.1` package for Agent, ReAct loop, Toolkit, permission context, `UserMsg` snapshots, and event type mapping.

The current implementation embeds the complete usable AgentScope 2 runtime path inside the OpenClaw backend: `Agent + OpenAIChatModel + Toolkit + AgentState + permission context + streamed AS2 events`. The official `agentscope.app` FastAPI service layer is detected as optional infrastructure; this repo keeps the public API as a lightweight stdlib REST/SSE service so the frontend stays decoupled and the MVP remains easy to run.

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
- `BYPASS`: non-denied mutating actions are allowed in the sandboxed MVP.

## Project Layout

```text
backend/openclaw/
  as2_adapter.py
  as2_runtime.py
  audit.py
  models.py
  permissions.py
  planner.py
  server.py
  storage.py
docs/
  MVP_PLAN.md
frontend/
  app.js
  index.html
  styles.css
scripts/
  start_backend.sh
  start_frontend.sh
tests/
  test_permissions.py
  test_planner.py
  test_server.py
```

## Test

```bash
.venv/bin/python -m unittest discover -s tests
```

## AgentScope 2 Architecture

OpenClaw maps AS2 concepts to local modules as follows:

- AS2 Agent/ReAct runtime: `backend/openclaw/as2_runtime.py`
- AS2 Toolkit tools: `openclaw_audit_schema`, `openclaw_workspace_inventory`, `openclaw_permission_probe`, `openclaw_score_candidate`
- AS2 session/workspace state: `build_as2_agent_state()`
- AS2 event bridge: local events carry `as2_event_type` and AS2 model events are persisted as `as2_model_event`
- OpenClaw control plane: `planner.py`, `permissions.py`, `storage.py`, and `audit.py`

The model-backed AS2 path proposes candidate steps, but OpenClaw still owns permission enforcement and audit persistence. If no provider key is configured or AS2 model execution fails, the planner falls back to deterministic local candidates and still writes a complete audit trail.

## Next Steps

- Add optional `agentscope.app` FastAPI/Redis service deployment for multi-session production hosting.
- Add user authentication and tenant-scoped storage.
- Persist approval rules and human confirmation events.
- Add real workspace tool execution in Docker/E2B rather than MVP simulation.
