import { createHash, randomUUID } from "node:crypto";
import type { DatabaseSync } from "node:sqlite";
import { resolveContextIndexConfig, stageTypePriority, type ResolvedContextIndexConfig } from "./config.js";
import { openContextIndexDatabase } from "./store.js";
import type {
  ContextAuditEvent,
  ContextInjection,
  ContextItem,
  ContextOutcome,
  ContextQuery,
  ContextRecord,
  ContextStage,
  ContextStatus,
  ContextType,
  RetrievedContext,
  SemanticScorer,
} from "./types.js";

type ContextRow = {
  id: string;
  content: string;
  summary: string;
  context_type: ContextType;
  project_id: string;
  task_id: string | null;
  keywords_json: string;
  entities_json: string;
  importance: number;
  confidence: number;
  status: ContextStatus;
  source: string;
  source_ref: string | null;
  content_hash: string;
  created_at: number;
  updated_at: number;
  last_accessed_at: number | null;
  valid_from: number | null;
  valid_until: number | null;
  superseded_by: string | null;
  metadata_json: string;
};

type AuditRow = {
  id: string;
  event_type: ContextAuditEvent["eventType"];
  context_id: string | null;
  project_id: string | null;
  task_id: string | null;
  session_id: string | null;
  reason: string | null;
  score: number | null;
  token_count: number | null;
  content_hash: string | null;
  timestamp: number;
  metadata_json: string;
};

const DEFAULT_SEMANTIC_SCORER: SemanticScorer = { score: () => 0 };

function jsonArray(value: string): string[] {
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) && parsed.every((item) => typeof item === "string") ? parsed : [];
  } catch {
    return [];
  }
}

function jsonObject(value: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function textTokens(input: string): string[] {
  return Array.from(
    new Set(
      input
        .toLocaleLowerCase()
        .match(/[\p{L}\p{N}_-]{2,}/gu)
        ?.slice(0, 40) ?? [],
    ),
  );
}

function summarize(content: string): string {
  const normalized = content.replace(/\s+/g, " ").trim();
  return normalized.length <= 280 ? normalized : `${normalized.slice(0, 277)}...`;
}

function clampUnit(value: number | undefined, fallback: number): number {
  return Math.max(0, Math.min(1, value ?? fallback));
}

function estimatedTokens(value: string): number {
  return Math.max(1, Math.ceil(value.length / 4));
}

function statusForQuery(query: ContextQuery): ContextStatus[] {
  const allowed: ContextStatus[] = ["active"];
  if (query.includeArchived) {
    allowed.push("archived");
  }
  if (query.includeSuperseded) {
    allowed.push("superseded");
  }
  return allowed;
}

function toRecord(row: ContextRow): ContextRecord {
  return {
    id: row.id,
    content: row.content,
    summary: row.summary,
    type: row.context_type,
    projectId: row.project_id,
    taskId: row.task_id ?? undefined,
    keywords: jsonArray(row.keywords_json),
    entities: jsonArray(row.entities_json),
    importance: row.importance,
    confidence: row.confidence,
    status: row.status,
    source: row.source,
    ...(row.source_ref ? { sourceRef: row.source_ref } : {}),
    contentHash: row.content_hash,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    ...(row.last_accessed_at ? { lastAccessedAt: row.last_accessed_at } : {}),
    ...(row.valid_from ? { validFrom: row.valid_from } : {}),
    ...(row.valid_until ? { validUntil: row.valid_until } : {}),
    ...(row.superseded_by ? { supersededBy: row.superseded_by } : {}),
    metadata: jsonObject(row.metadata_json),
  };
}

function relationTypeForStage(stage: ContextStage, type: ContextType): number {
  return stageTypePriority(stage, type) / 5;
}

export class ContextIndexManager {
  readonly #db: DatabaseSync;
  readonly #config: ResolvedContextIndexConfig;
  readonly #semanticScorer: SemanticScorer;

  constructor(params: {
    databasePath: string;
    config?: Parameters<typeof resolveContextIndexConfig>[0];
    semanticScorer?: SemanticScorer;
  }) {
    this.#db = openContextIndexDatabase(params.databasePath);
    this.#config = resolveContextIndexConfig(params.config);
    this.#semanticScorer = params.semanticScorer ?? DEFAULT_SEMANTIC_SCORER;
  }

  close(): void {
    this.#db.close();
  }

  index(item: ContextItem): ContextRecord {
    const content = item.content.trim();
    if (!content) {
      throw new Error("Context content must not be empty.");
    }
    const projectId = item.projectId?.trim() || this.#config.defaultProjectId || "agent:unknown";
    const taskId = item.taskId?.trim() || undefined;
    const contentHash = createHash("sha256").update(content).digest("hex");
    const duplicate = this.#db
      .prepare(
        "SELECT * FROM contexts WHERE project_id = ? AND task_id IS ? AND content_hash = ? ORDER BY created_at DESC LIMIT 1",
      )
      .get(projectId, taskId ?? null, contentHash) as ContextRow | undefined;
    if (duplicate) {
      if (item.supersedesId && item.supersedesId !== duplicate.id) {
        this.supersede(item.supersedesId, duplicate.id);
      }
      this.#audit({
        eventType: "context_skipped",
        contextId: duplicate.id,
        projectId,
        taskId,
        reason: "duplicate_content_hash",
        contentHash,
      });
      return toRecord(duplicate);
    }
    if (item.supersedesId) {
      const superseded = this.#db
        .prepare("SELECT id FROM contexts WHERE id = ?")
        .get(item.supersedesId) as { id: string } | undefined;
      if (!superseded) {
        throw new Error("Superseded context record must exist before indexing a replacement.");
      }
    }

    const now = item.createdAt ?? Date.now();
    const id = randomUUID();
    const keywords = Array.from(new Set([...(item.keywords ?? []), ...textTokens(content)])).slice(0, 64);
    const record: ContextRecord = {
      id,
      content,
      summary: item.summary?.trim() || summarize(content),
      type: item.type,
      projectId,
      ...(taskId ? { taskId } : {}),
      keywords,
      entities: Array.from(new Set(item.entities ?? [])).slice(0, 64),
      importance: clampUnit(item.importance, 0.5),
      confidence: clampUnit(item.confidence, 1),
      status: item.status ?? "active",
      source: item.source?.trim() || "context-index",
      ...(item.sourceRef?.trim() ? { sourceRef: item.sourceRef.trim() } : {}),
      contentHash,
      createdAt: now,
      updatedAt: now,
      ...(item.validFrom ? { validFrom: item.validFrom } : {}),
      ...(item.validUntil ? { validUntil: item.validUntil } : {}),
      metadata: item.metadata ?? {},
    };
    this.#db
      .prepare(
        `INSERT INTO contexts (
          id, content, summary, context_type, project_id, task_id, keywords_json, entities_json,
          importance, confidence, status, source, source_ref, content_hash, created_at, updated_at,
          valid_from, valid_until, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        record.id,
        record.content,
        record.summary,
        record.type,
        record.projectId,
        record.taskId ?? null,
        JSON.stringify(record.keywords),
        JSON.stringify(record.entities),
        record.importance,
        record.confidence,
        record.status,
        record.source,
        record.sourceRef ?? null,
        record.contentHash,
        record.createdAt,
        record.updatedAt,
        record.validFrom ?? null,
        record.validUntil ?? null,
        JSON.stringify(record.metadata),
      );
    this.#replaceFts(record);
    this.#audit({
      eventType: "context_indexed",
      contextId: record.id,
      projectId: record.projectId,
      taskId: record.taskId,
      contentHash: record.contentHash,
      reason: record.type,
    });
    if (item.supersedesId) {
      this.supersede(item.supersedesId, record.id);
    }
    return record;
  }

  supersede(oldContextId: string, newContextId: string): void {
    if (oldContextId === newContextId) {
      throw new Error("A context record cannot supersede itself.");
    }
    const now = Date.now();
    this.#db.exec("BEGIN IMMEDIATE");
    try {
      const oldRecord = this.#db.prepare("SELECT id FROM contexts WHERE id = ?").get(oldContextId);
      const newRecord = this.#db.prepare("SELECT id FROM contexts WHERE id = ?").get(newContextId);
      if (!oldRecord || !newRecord) {
        throw new Error("Both context records must exist before superseding.");
      }
      this.#db
        .prepare("UPDATE contexts SET status = 'superseded', superseded_by = ?, updated_at = ? WHERE id = ?")
        .run(newContextId, now, oldContextId);
      this.#db
        .prepare(
          "INSERT OR IGNORE INTO context_relations (from_context_id, to_context_id, relation_type, created_at) VALUES (?, ?, 'supersedes', ?)",
        )
        .run(newContextId, oldContextId, now);
      this.#db.exec("COMMIT");
    } catch (error) {
      this.#db.exec("ROLLBACK");
      throw error;
    }
    this.#audit({
      eventType: "context_superseded",
      contextId: oldContextId,
      reason: "explicit_supersede",
      metadata: { replacementContextId: newContextId },
    });
  }

  retrieve(query: ContextQuery): RetrievedContext[] {
    const now = query.nowMs ?? Date.now();
    const candidates = this.#loadCandidates(query);
    const queryTokens = textTokens(query.userQuery);
    const results = candidates
      .map((record) => this.#score(query, record, queryTokens, now))
      .filter((result): result is RetrievedContext => result !== null)
      .toSorted((left, right) => right.score - left.score || right.record.createdAt - left.record.createdAt)
      .slice(0, query.maxResults ?? this.#config.retrieval.topK);
    this.#audit({
      eventType: "context_query_created",
      projectId: query.projectId,
      taskId: query.taskId,
      reason: query.stage,
      metadata: { candidateCount: candidates.length, resultCount: results.length },
    });
    for (const result of results) {
      this.#db
        .prepare("UPDATE contexts SET last_accessed_at = ? WHERE id = ?")
        .run(now, result.record.id);
      this.#db
        .prepare(
          "INSERT INTO context_access_log (id, context_id, project_id, task_id, stage, score, token_count, accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .run(
          randomUUID(),
          result.record.id,
          query.projectId,
          query.taskId ?? null,
          query.stage,
          result.score,
          result.estimatedTokens,
          now,
        );
      this.#audit({
        eventType: "context_retrieved",
        contextId: result.record.id,
        projectId: query.projectId,
        taskId: query.taskId,
        reason: result.reasons.join(","),
        score: result.score,
        contentHash: result.record.contentHash,
      });
    }
    return results;
  }

  buildInjection(query: ContextQuery, stage: ContextStage, tokenBudget: number): ContextInjection {
    const selected = this.retrieve({ ...query, stage });
    const ordered = selected.toSorted((left, right) => {
      const priorityDelta = stageTypePriority(stage, right.record.type) - stageTypePriority(stage, left.record.type);
      return priorityDelta || right.score - left.score || right.record.createdAt - left.record.createdAt;
    });
    let remaining = Math.max(0, tokenBudget);
    const kept: RetrievedContext[] = [];
    const skipped: ContextInjection["skipped"] = [];
    for (const hit of ordered) {
      const snippet = this.#renderSnippet(hit.record);
      const tokens = estimatedTokens(snippet);
      if (tokens > remaining) {
        skipped.push({ contextId: hit.record.id, reason: "token_budget" });
        this.#audit({
          eventType: "context_filtered",
          contextId: hit.record.id,
          projectId: query.projectId,
          taskId: query.taskId,
          reason: "token_budget",
          score: hit.score,
          tokenCount: tokens,
          contentHash: hit.record.contentHash,
        });
        continue;
      }
      kept.push({ ...hit, estimatedTokens: tokens });
      remaining -= tokens;
      this.#audit({
        eventType: "context_injected",
        contextId: hit.record.id,
        projectId: query.projectId,
        taskId: query.taskId,
        reason: stage,
        score: hit.score,
        tokenCount: tokens,
        contentHash: hit.record.contentHash,
      });
    }
    return {
      stage,
      prompt: this.#renderPrompt(kept),
      selected: kept,
      skipped,
      estimatedTokens: tokenBudget - remaining,
      truncated: skipped.length > 0,
    };
  }

  buildBaselineInjection(query: ContextQuery, tokenBudget: number): ContextInjection {
    return this.buildInjection(
      { ...query, includeArchived: true, includeSuperseded: true, maxResults: 10_000 },
      query.stage,
      tokenBudget,
    );
  }

  recordOutcome(outcome: ContextOutcome): void {
    const timestamp = outcome.timestamp ?? Date.now();
    this.#audit({
      eventType: "context_archived",
      projectId: outcome.projectId,
      taskId: outcome.taskId,
      sessionId: outcome.sessionId,
      reason: outcome.outcome,
      metadata: { hasSummary: Boolean(outcome.summary?.trim()), timestamp },
    });
  }

  listAuditEvents(limit = 100): ContextAuditEvent[] {
    return (this.#db
      .prepare("SELECT * FROM context_audit_events ORDER BY timestamp DESC LIMIT ?")
      .all(limit) as AuditRow[])
      .map((row) => ({
        id: row.id,
        eventType: row.event_type,
        ...(row.context_id ? { contextId: row.context_id } : {}),
        ...(row.project_id ? { projectId: row.project_id } : {}),
        ...(row.task_id ? { taskId: row.task_id } : {}),
        ...(row.session_id ? { sessionId: row.session_id } : {}),
        ...(row.reason ? { reason: row.reason } : {}),
        ...(row.score !== null ? { score: row.score } : {}),
        ...(row.token_count !== null ? { tokenCount: row.token_count } : {}),
        ...(row.content_hash ? { contentHash: row.content_hash } : {}),
        timestamp: row.timestamp,
        metadata: jsonObject(row.metadata_json),
      }));
  }

  #loadCandidates(query: ContextQuery): ContextRecord[] {
    const statuses = statusForQuery(query);
    const placeholders = statuses.map(() => "?").join(", ");
    const typeClause = query.contextTypes?.length
      ? ` AND context_type IN (${query.contextTypes.map(() => "?").join(", ")})`
      : "";
    const taskClause = query.strictTask && query.taskId ? " AND (task_id = ? OR task_id IS NULL)" : "";
    const rows = this.#db
      .prepare(
        `SELECT * FROM contexts WHERE project_id = ? AND status IN (${placeholders})${typeClause}${taskClause} ORDER BY created_at DESC LIMIT ?`,
      )
      .all(
        query.projectId,
        ...statuses,
        ...(query.contextTypes ?? []),
        ...(query.strictTask && query.taskId ? [query.taskId] : []),
        query.candidateK ?? this.#config.retrieval.candidateK,
      ) as ContextRow[];
    const fallback = rows.map(toRecord);
    const ftsMatches = this.#findFtsCandidates(query, statuses);
    const byId = new Map(ftsMatches.map((record) => [record.id, record]));
    for (const record of fallback) {
      byId.set(record.id, record);
    }
    return Array.from(byId.values()).slice(0, query.candidateK ?? this.#config.retrieval.candidateK);
  }

  #findFtsCandidates(query: ContextQuery, statuses: ContextStatus[]): ContextRecord[] {
    const terms = textTokens(query.userQuery)
      .map((term) => term.replaceAll("-", ""))
      .filter(Boolean)
      .slice(0, 12);
    if (terms.length === 0) {
      return [];
    }
    try {
      const ids = this.#db
        .prepare("SELECT context_id FROM contexts_fts WHERE contexts_fts MATCH ? LIMIT ?")
        .all(terms.join(" OR "), query.candidateK ?? this.#config.retrieval.candidateK) as Array<{
        context_id: string;
      }>;
      if (ids.length === 0) {
        return [];
      }
      const idPlaceholders = ids.map(() => "?").join(", ");
      const statusPlaceholders = statuses.map(() => "?").join(", ");
      const typeClause = query.contextTypes?.length
        ? ` AND context_type IN (${query.contextTypes.map(() => "?").join(", ")})`
        : "";
      const taskClause = query.strictTask && query.taskId ? " AND (task_id = ? OR task_id IS NULL)" : "";
      const rows = this.#db
        .prepare(
          `SELECT * FROM contexts WHERE id IN (${idPlaceholders}) AND project_id = ? AND status IN (${statusPlaceholders})${typeClause}${taskClause}`,
        )
        .all(
          ...ids.map((item) => item.context_id),
          query.projectId,
          ...statuses,
          ...(query.contextTypes ?? []),
          ...(query.strictTask && query.taskId ? [query.taskId] : []),
        ) as ContextRow[];
      return rows.map(toRecord);
    } catch {
      // FTS5 is an optional candidate accelerator; deterministic field and keyword scoring still work.
      return [];
    }
  }

  #score(
    query: ContextQuery,
    record: ContextRecord,
    queryTokens: string[],
    nowMs: number,
  ): RetrievedContext | null {
    if (record.validFrom && record.validFrom > nowMs) {
      return null;
    }
    if (record.validUntil && record.validUntil < nowMs && record.status === "active") {
      return null;
    }
    const haystack = new Set([...record.keywords, ...textTokens(record.summary)]);
    const keywordScore =
      queryTokens.length === 0 ? 0 : queryTokens.filter((token) => haystack.has(token)).length / queryTokens.length;
    const scopeScore = record.taskId && query.taskId ? (record.taskId === query.taskId ? 1 : 0.2) : 0.7;
    const stageScore = relationTypeForStage(query.stage, record.type);
    const ageDays = Math.max(0, nowMs - record.createdAt) / 86_400_000;
    const recencyScore = Math.exp((-Math.LN2 * ageDays) / this.#config.retrieval.halfLifeDays);
    const validityScore = record.status === "active" ? 1 : record.status === "archived" ? 0.35 : 0;
    const score =
      keywordScore * this.#config.scoring.keywordWeight +
      scopeScore * this.#config.scoring.scopeWeight +
      stageScore * this.#config.scoring.stageWeight +
      recencyScore * this.#config.scoring.recencyWeight +
      record.importance * this.#config.scoring.importanceWeight +
      validityScore * this.#config.scoring.validityWeight +
      this.#semanticScorer.score(query, record);
    return {
      record,
      score,
      reasons: [
        `keyword:${keywordScore.toFixed(2)}`,
        `scope:${scopeScore.toFixed(2)}`,
        `stage:${stageScore.toFixed(2)}`,
        `recency:${recencyScore.toFixed(2)}`,
      ],
      estimatedTokens: estimatedTokens(this.#renderSnippet(record)),
    };
  }

  #renderSnippet(record: ContextRecord): string {
    const content = record.content.length > this.#config.maxSnippetChars
      ? `${record.content.slice(0, this.#config.maxSnippetChars - 3)}...`
      : record.content;
    return `- (${record.type}; ${record.id}) ${content}`;
  }

  #renderPrompt(records: RetrievedContext[]): string {
    const buckets: Record<string, RetrievedContext[]> = {
      "Stable Rules": [],
      "Project Context": [],
      "Task Context": [],
      "Retrieved Evidence": [],
      "Conflict Notice": [],
    };
    for (const record of records) {
      const target =
        record.record.type === "stable_rule" || record.record.type === "user_preference"
          ? "Stable Rules"
          : record.record.type === "project_overview" || record.record.type === "decision"
            ? "Project Context"
            : record.record.type === "task_state" || record.record.type === "task_record"
              ? "Task Context"
              : "Retrieved Evidence";
      buckets[target].push(record);
    }
    return Object.entries(buckets)
      .filter(([, values]) => values.length > 0)
      .map(([label, values]) => `[${label}]\n${values.map((value) => this.#renderSnippet(value.record)).join("\n")}`)
      .join("\n\n");
  }

  #replaceFts(record: ContextRecord): void {
    this.#db.prepare("DELETE FROM contexts_fts WHERE context_id = ?").run(record.id);
    this.#db
      .prepare("INSERT INTO contexts_fts (context_id, content, summary, keywords) VALUES (?, ?, ?, ?)")
      .run(record.id, record.content, record.summary, record.keywords.join(" "));
  }

  #audit(event: Omit<ContextAuditEvent, "id" | "timestamp" | "metadata"> & { metadata?: Record<string, unknown> }): void {
    if (!this.#config.audit.enabled) {
      return;
    }
    this.#db
      .prepare(
        `INSERT INTO context_audit_events (
          id, event_type, context_id, project_id, task_id, session_id, reason,
          score, token_count, content_hash, timestamp, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        randomUUID(),
        event.eventType,
        event.contextId ?? null,
        event.projectId ?? null,
        event.taskId ?? null,
        event.sessionId ?? null,
        event.reason ?? null,
        event.score ?? null,
        event.tokenCount ?? null,
        event.contentHash ?? null,
        Date.now(),
        JSON.stringify(event.metadata ?? {}),
      );
  }
}
