# Context Index

`context-index` is a local OpenClaw ContextEngine plugin for Direction 2, The Architect. It moves historical context into a structured SQLite index, retrieves only task-relevant records at model-call time, and records retrieval decisions without copying sensitive source text into audit logs.

## Install and enable

```bash
openclaw plugins install -l ./context_index
```

```json5
{
  plugins: {
    slots: { contextEngine: "context-index" },
    entries: {
      "context-index": {
        enabled: true,
        config: {
          mode: "progressive",
          defaultProjectId: "capstone-direction-2",
          retrieval: { topK: 8, candidateK: 80, halfLifeDays: 30 },
          recentMessageLimit: 8,
          maxSnippetChars: 900,
          audit: { enabled: true }
        }
      }
    }
  }
}
```

Restart the Gateway after changing the selected ContextEngine.

## Behavior

- `assemble()` indexes any pre-existing visible history idempotently, retrieves scoped records, and adds structured sections to the system prompt.
- `progressive` preserves only recent session messages and excludes superseded records by default.
- `baseline` includes active, archived, and superseded records in the same scope for a deterministic comparison, still bounded by the supplied token budget.
- A subsequent model call after a tool failure searches with the `tool_error` stage; replanning messages use `replan`.
- `afterTurn()` archives newly produced conversation, tool-result, error, decision, rule, and reflection records.

The plugin requires a ContextEngine host with `assemble-before-prompt`, such as OpenClaw's embedded or Codex runtimes. It delegates compaction to the standard runtime.

## Explicit import and audit

The MVP imports UTF-8 Markdown, text, and JSON only. Project and task identity are explicit at import time.

```bash
openclaw context-index import ./project-requirements.md \
  --project capstone-direction-2 \
  --task context-index \
  --type document \
  --importance 0.8

openclaw context-index audit --json
```

Use `--supersedes <context-id>` when a new record explicitly replaces a prior decision or constraint. The plugin does not infer replacement relationships automatically.

## Storage and privacy

Each agent owns `<agentDir>/context-index.sqlite`. It contains structured records, explicit relations, access metadata, audit events, and an FTS5 candidate index. Audit events store IDs, scope, score, reason, token count, timestamp, and content hash only; they do not store source bodies or generated summaries.

## Development evidence

```bash
pnpm test
pnpm benchmark -- --out-dir artifacts
```

The benchmark generates a synthetic JSON-to-YAML constraint update with distractors. Its `task_accuracy` is a deterministic retrieval/injection oracle, not an end-to-end model-quality claim.
