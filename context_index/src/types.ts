export const CONTEXT_TYPES = [
  "stable_rule",
  "user_preference",
  "project_overview",
  "decision",
  "task_state",
  "task_record",
  "conversation",
  "tool_result",
  "error",
  "reflection",
  "document",
] as const;

export const CONTEXT_STATUSES = ["active", "archived", "superseded", "expired", "invalid"] as const;

export const CONTEXT_STAGES = ["initial", "tool_error", "replan", "tool", "reflection"] as const;

export type ContextType = (typeof CONTEXT_TYPES)[number];
export type ContextStatus = (typeof CONTEXT_STATUSES)[number];
export type ContextStage = (typeof CONTEXT_STAGES)[number];

export type ContextItem = {
  content: string;
  type: ContextType;
  projectId?: string;
  taskId?: string;
  summary?: string;
  keywords?: string[];
  entities?: string[];
  importance?: number;
  confidence?: number;
  status?: ContextStatus;
  source?: string;
  sourceRef?: string;
  createdAt?: number;
  validFrom?: number;
  validUntil?: number;
  supersedesId?: string;
  metadata?: Record<string, unknown>;
};

export type ContextRecord = Omit<
  Required<
  Pick<
    ContextItem,
    | "content"
    | "type"
    | "projectId"
    | "taskId"
    | "summary"
    | "keywords"
    | "entities"
    | "importance"
    | "confidence"
    | "status"
    | "source"
    | "createdAt"
  >
  >,
  "projectId" | "taskId"
> & {
  id: string;
  projectId: string;
  taskId?: string;
  sourceRef?: string;
  updatedAt: number;
  lastAccessedAt?: number;
  validFrom?: number;
  validUntil?: number;
  supersededBy?: string;
  contentHash: string;
  metadata: Record<string, unknown>;
};

export type ContextQuery = {
  userQuery: string;
  projectId: string;
  taskId?: string;
  stage: ContextStage;
  contextTypes?: ContextType[];
  strictTask?: boolean;
  maxResults?: number;
  candidateK?: number;
  includeArchived?: boolean;
  includeSuperseded?: boolean;
  nowMs?: number;
};

export type RetrievedContext = {
  record: ContextRecord;
  score: number;
  reasons: string[];
  estimatedTokens: number;
};

export type ContextInjection = {
  stage: ContextStage;
  prompt: string;
  selected: RetrievedContext[];
  skipped: Array<{ contextId: string; reason: string }>;
  estimatedTokens: number;
  truncated: boolean;
};

export type ContextOutcome = {
  projectId: string;
  taskId?: string;
  sessionId: string;
  outcome: "completed" | "failed" | "aborted";
  summary?: string;
  timestamp?: number;
};

export type ContextAuditEvent = {
  id: string;
  eventType:
    | "context_indexed"
    | "context_query_created"
    | "context_retrieved"
    | "context_filtered"
    | "context_injected"
    | "context_archived"
    | "context_superseded"
    | "context_skipped";
  contextId?: string;
  projectId?: string;
  taskId?: string;
  sessionId?: string;
  reason?: string;
  score?: number;
  tokenCount?: number;
  contentHash?: string;
  timestamp: number;
  metadata: Record<string, unknown>;
};

export type SemanticScorer = {
  score(query: ContextQuery, record: ContextRecord): number;
};
