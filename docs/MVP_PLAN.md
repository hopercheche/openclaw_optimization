# OpenClawPOpti AS2 Audit MVP Plan

## Goal

Build a runnable MVP for an audit-first agent planning console based on AgentScope 2 design ideas. The MVP must keep frontend and backend decoupled, expose a traceable planner workflow, and persist enough evidence for post-run review.

## Design Basis

AgentScope 2 features to mirror in the MVP:

- Typed event stream: every planning, permission, tool, critique, and final-response step is emitted as an event.
- Permission gate: every tool/action request is classified as `allow`, `ask`, or `deny`.
- Workspace boundary: runs execute against a scoped workspace path instead of arbitrary host paths.
- Session-oriented service: each run gets a stable `run_id`, persisted events, and an audit report.
- Planner/team direction: use a leader-planner style loop with verifier critique before final output.

Planner methods to incorporate:

- ReAct: alternate reasoning and acting so every action has an observable rationale.
- Plan-and-Execute: decompose the task into steps before acting.
- Reflexion/Self-Refine: critique each step and record improvement notes.
- Tree-of-Thoughts, bounded for MVP: generate alternative candidate steps and score/prune to keep cost predictable.

## MVP Scope

### Backend

- Python standard-library HTTP service, so the MVP runs without dependency installation.
- REST endpoints:
  - `GET /api/health`
  - `POST /api/runs`
  - `GET /api/runs`
  - `GET /api/runs/{run_id}`
  - `GET /api/runs/{run_id}/events`
  - `GET /api/runs/{run_id}/audit.md`
- SSE endpoint:
  - `GET /api/runs/{run_id}/stream`
- Persistent files:
  - `data/runs/{run_id}/events.jsonl`
  - `data/runs/{run_id}/state.json`
  - `data/runs/{run_id}/audit.md`

### Frontend

- Static HTML/CSS/JS under `frontend/`.
- Calls backend APIs directly.
- Shows:
  - task input
  - permission mode
  - run status
  - live event timeline
  - planner steps and critiques
  - audit report link/content

### AgentScope 2 Runtime Layer

- Keep the runtime behind an interface so an AS2 app service can later replace the lightweight stdlib REST/SSE service.
- Include an `as2_adapter` module that imports the real `agentscope` package, reports capability status, maps local events to AS2 event types, and builds AS2 `UserMsg` snapshots.
- Include an `as2_runtime` module that builds a real AS2 `Agent`, `OpenAIChatModel`, `Toolkit`, `AgentState`, permission context, and ReAct loop when model credentials are configured.
- Preserve AS2-compatible concepts in data models: event type, session/run id, workspace id, permission decision, tool call/result, and audit report.

## Backend Architecture

```text
backend/
  openclaw/
    server.py          # HTTP app and routing
    models.py          # dataclasses and serialization
    planner.py         # bounded audit planner
    audit.py           # Markdown audit rendering
    storage.py         # JSON/JSONL file store
    permissions.py     # allow/ask/deny decision engine
    as2_adapter.py     # optional AgentScope integration boundary
    as2_runtime.py     # real AgentScope Agent/Toolkit runtime
```

Runtime flow:

```text
POST /api/runs
  -> create run state
  -> planner emits typed events
  -> permission gate reviews candidate actions
  -> verifier critiques each step
  -> storage writes events/state/audit
  -> frontend polls or streams events
```

## Planner Shape

For MVP, the planner is deterministic and auditable:

1. Normalize the user goal.
2. Generate candidate plan steps from a small strategy library.
3. Score candidate steps on impact, safety, reversibility, and evidence value.
4. Keep the top bounded steps.
5. For each step:
   - emit `reasoning`
   - request permission for the associated action
   - emit `permission`
   - simulate safe tool execution for MVP
   - emit `tool_result`
   - run verifier critique
   - emit `critique`
6. Emit final recommendation and audit report.

This gives us a testable planner with a real LLM/AS2 ReAct agent path and a deterministic fallback.

## Acceptance Criteria

- `python3 backend/openclaw/server.py` starts the API.
- `python3 -m http.server 4173 --directory frontend` serves the frontend.
- Creating a run produces a stable `run_id`.
- Events are visible through REST and SSE.
- An audit Markdown report is written for every run.
- Permission mode changes planner decisions.
- Tests cover planner, permissions, storage, and API smoke paths.

## Implementation Order

1. Create this plan document.
2. Implement backend modules and CLI server.
3. Implement static frontend.
4. Add README, sample run instructions, and lightweight tests.
5. Run tests and smoke start the backend/frontend.

## Known Constraints

- Current machine has Python 3.13 but no Node/npm.
- `agentscope==2.0.1` is installed in `.venv`.
- The first version is an embedded AS2 Agent/Toolkit audit runtime, not the optional `agentscope.app` FastAPI service.
- The optional `agentscope.app` service layer needs extra app-server dependencies such as FastAPI, Redis transport/storage, and scheduler support; the MVP exposes a stdlib REST/SSE API instead.
- When `DEEPSEEK_API_KEY` or another OpenAI-compatible key is present, the planner asks a real AS2 `Agent` backed by `OpenAIChatModel` and an OpenClaw Toolkit to generate candidate steps, then keeps local permission/audit enforcement in control.
