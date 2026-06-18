# OpenClaw AgentScope 2 Architecture

OpenClaw now embeds the runnable AgentScope 2 agent architecture inside the backend while keeping the public frontend/backend boundary simple.

## Runtime Stack

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

## Code Mapping

- `backend/openclaw/as2_adapter.py`: package detection, provider config, AS2 event mapping, permission-mode mapping.
- `backend/openclaw/as2_runtime.py`: complete embedded AS2 runtime with `Agent`, `Toolkit`, `AgentState`, permission context, ReAct loop, and model event capture.
- `backend/openclaw/planner.py`: OpenClaw control plane. It asks AS2 for candidate steps when the model runtime is ready, then keeps permission and audit enforcement local.
- `backend/openclaw/permissions.py`: allow/ask/deny policy for every proposed action.
- `backend/openclaw/storage.py`: run state and event persistence.
- `backend/openclaw/audit.py`: Markdown audit report rendering.
- `frontend/app.js`: live event timeline over SSE.

## AS2 Toolkit

The embedded runtime registers four read-only OpenClaw tools:

- `openclaw_audit_schema`: returns the planner JSON schema and scoring formula.
- `openclaw_workspace_inventory`: lists scoped workspace entries without reading secrets or mutating files.
- `openclaw_permission_probe`: previews OpenClaw allow/ask/deny behavior for a proposed action.
- `openclaw_score_candidate`: scores a candidate by impact, evidence value, reversibility, and risk.

These tools let the AS2 agent reason with real runtime affordances while keeping side effects under OpenClaw control.

## App Service Boundary

AgentScope 2.0.1 also ships an optional `agentscope.app` FastAPI service stack with Redis-backed storage/message bus and workspace managers. The current environment does not have those optional app-server dependencies installed, so OpenClaw exposes a lightweight stdlib REST/SSE service and embeds the Agent/Toolkit runtime directly.

Use `GET /api/as2/architecture` to inspect which AS2 components are importable and active.
