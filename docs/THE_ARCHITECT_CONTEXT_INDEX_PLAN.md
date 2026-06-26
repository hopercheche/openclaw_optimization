# OpenClaw The Architect: Context Index Architecture and 7-Week Plan

## 1. Direction 2 Design Rationale

### 1.1 Goal

This direction focuses on long-term context management for OpenClaw Agent. Traditional compaction compresses historical conversations into shorter summaries, which can easily lose earlier but still important information. Therefore, this direction proposes turning the context layer from compressed text into a searchable, traceable, and structured context index.

The goals are:

- Long-range recall: goals, key events, and conclusions from earlier runs can be retrieved by later tasks.
- Low-noise injection: only the context snippets needed for the current reasoning step are injected into the prompt, instead of loading all history.
- Auditability: every retrieval, injection, and archival operation is written into audit events.
- Modularity: the context layer can be integrated with the planner and AS2 runtime without tightly coupling to either.

### 1.2 Core Idea

This direction does not implement context as traditional compaction. Instead, it uses an Archival Context Index:

```text
historical runs / audit events / final responses
        -> context archival
        -> SQLite FTS index
        -> goal-aware retrieval
        -> structured context snippets
        -> planner / AS2 prompt injection
        -> new run evidence
        -> archive back to index
```

The model does not rely on a continuously shortened historical summary. At the beginning of each run, the runtime retrieves relevant historical snippets from the long-term index according to the current goal. Injected context contains source, timestamp, run_id, snippet text, and metadata, reducing both long-context information loss and unsupported memory hallucination.

## 2. System Architecture

### 2.1 Context Archival Layer

This layer archives valuable context after each run is completed.

Archived objects include:

- user goal
- selected planner steps
- key audit events
- critique notes
- final response
- run metadata

Each archived record is structured as:

```text
record_id
run_id
kind: goal / planning / critique / final
title
body
source
created_at
metadata_json
```

The purpose of this layer is to convert one-time run logs into long-term memory that can be recalled later.

### 2.2 Context Index Layer

The first version uses SQLite FTS as the index backend.

SQLite FTS is selected because:

- It is local and reproducible, with no external vector database required.
- It is suitable for a course PR because it has low dependency and deployment cost.
- It supports keyword and phrase retrieval, which is enough to validate whether old information can be recalled.
- It preserves run_id and source metadata for auditability.

If the local SQLite build does not support FTS5, the system should fall back to LIKE-based retrieval so the runtime remains usable.

### 2.3 Retrieval Layer

At the beginning of a new run, the runtime builds a query from the current goal and retrieves the top-k historical snippets from the context index.

Retrieval should follow these constraints:

- Return 3-5 snippets by default.
- Limit each snippet length to avoid recreating context bloat.
- Return only source-backed records, not free-form memory summaries without metadata.
- Write retrieval results into a `context_retrieval` audit event.

### 2.4 Structured Injection Layer

Retrieved records are converted into structured context and injected into the planner or AS2 prompt.

Example:

```json
{
  "retrieved_context": [
    {
      "run_id": "run_xxx",
      "kind": "final",
      "title": "Previous planner conclusion",
      "snippet": "...",
      "source": "context_index",
      "created_at": "..."
    }
  ]
}
```

The principle is that context is injected as source-backed evidence, not as unverifiable compressed memory.

### 2.5 Audit and Feedback Layer

The system should record three new audit event types:

- `context_retrieval`: which historical records were retrieved for the current query.
- `context_injection`: which snippets were injected into the planner or AS2 prompt.
- `context_archived`: which contents from the current run were archived.

These events can be used as midterm report evidence and screenshot evidence.

## 3. Data and Evaluation Plan

### 3.1 Data Source

The first version does not introduce an external dataset. It uses OpenClaw's own runtime history:

- planner runs
- audit events
- final responses
- manually designed long-recall test cases

### 3.2 Success Criteria

The first stage focuses on long-range recall rather than a full benchmark.

Core criteria:

- Recall hit: a later task can retrieve key information from an earlier run.
- Source traceability: each injected context item can be traced back to a run_id and event source.
- Context efficiency: the system injects a small number of snippets instead of the full history.
- Runtime compatibility: the change does not break the existing planner, AS2 runtime, or audit flow.

### 3.3 Expected Outcomes

- A pluggable context index module.
- A SQLite FTS long-term context index.
- Automatic retrieval and injection inside the planner runtime.
- Audit reports showing context retrieval, injection, and archival events.
- Unit and integration tests proving long-range recall works.

## 4. Implementation Phases

### Phase 1: MVP Context Index

Work items:

1. Implement `context_index.py`.
2. Create the SQLite FTS schema.
3. Support archive, search, and snippet rendering.
4. Provide fallback retrieval when FTS5 is unavailable.

Deliverables:

- A runnable local context index.
- Basic retrieval interface.
- Unit tests for the context index.

### Phase 2: Planner Integration

Work items:

1. Run retrieval at the beginning of `LocalAuditPlanner.run()`.
2. Write retrieval results into audit events.
3. Inject snippets into deterministic planner candidate generation.
4. Archive the current run after it completes.

Deliverables:

- Planner-level context recall prototype.
- `context_retrieval`, `context_injection`, and `context_archived` events.
- Cross-run recall tests.

### Phase 3: AS2 Prompt Injection

Work items:

1. Extend `generate_as2_openai_plan()` with an optional retrieved context parameter.
2. Add `retrieved_context` to the AS2 user prompt.
3. Constrain the system prompt so the model only uses source-backed historical context.
4. Keep fallback behavior working when no provider key is configured.

Deliverables:

- AS2 runtime can consume long-term context.
- Model-backed planner and deterministic planner share the same context layer.

### Phase 4: Evidence and Report Preparation

Work items:

1. Prepare long-range recall example runs.
2. Capture audit screenshots or event JSON.
3. Document Direction 2 in the README.
4. Summarize limitations and future benchmark plans.

Deliverables:

- Evidence for the midterm report.
- Direction 2 architecture explanation.
- PR description materials.

## 5. Seven-Week Plan

| Time | Plan |
| --- | --- |
| Week 1 | Start the project and define the Direction 2 goal: avoid long-term information loss caused by traditional compaction, and adopt context index plus structured injection. |
| Week 2 | Read related materials and refine requirements. Use MemGPT, Letta, and progressive disclosure as references. Confirm SQLite FTS as the first index backend. |
| Week 3 | Complete the system architecture design. Implement the MVP Context Index, including archival, retrieval, snippet rendering, and fallback search. |
| Week 4 | Integrate the planner runtime. Implement automatic retrieval at run start, structured injection, and automatic archival at run completion. Prepare midterm report materials. |
| Week 5 | Integrate AS2 prompt injection so the model-backed planner can also read retrieved context. Add audit events and README documentation. |
| Week 6 | Design long-range recall test cases. Improve unit and integration tests to verify that earlier run information can be recalled by later related tasks. |
| Week 7 | Optimize the overall system and documentation. Prepare screenshots, audit evidence, architecture diagrams, limitation analysis, and future benchmark plans for the final report. |

## 6. Risks and Limitations

- SQLite FTS is lexical retrieval and cannot fully cover semantic similarity; embedding-based reranking can be added later.
- Too many snippets may still cause context pollution, so the first version must limit top-k and snippet length.
- Index quality depends on the quality of historical run events.
- The first version does not include a full benchmark. It only proves that the core context recall pipeline works.

## 7. Mapping to Midterm Report Requirements

| Midterm report requirement | Direction 2 content |
| --- | --- |
| Project overview and problem statement | Solve long-term context forgetting in agent workflows. |
| Requirements and success criteria | Long-range recall, structured injection, auditability, and low-noise context. |
| Technical approach and architecture | SQLite FTS context index plus retrieval, injection, and audit events. |
| Progress and implemented work | Use the PR prototype, tests, and audit events as evidence. |
| Evidence and evaluation | Show cross-run recall tests, event logs, and sample outputs. |
| Challenges, risks, and limitations | FTS has limited semantic capability; context pollution risk; index quality depends on historical data. |
| Plan to final delivery | Follow the 7-week plan, then add benchmark and vector retrieval improvements later. |

## 8. AI / Tool-Use Disclosure

AI tools were used to assist with this architecture planning:

- Extracting the required report structure from the midterm requirements.
- Reusing the section style of the Direction 1 architecture template.
- Organizing the Direction 2 idea into technical architecture, implementation phases, and a 7-week plan.
- The final content should still be reviewed by team members against actual implementation progress, code evidence, and test results.
