import type { ContextStage } from "./types.js";

export type ContextIndexPluginConfig = {
  mode?: "baseline" | "progressive";
  defaultProjectId?: string;
  recentMessageLimit?: number;
  maxSnippetChars?: number;
  retrieval?: {
    topK?: number;
    candidateK?: number;
    halfLifeDays?: number;
  };
  scoring?: {
    keywordWeight?: number;
    scopeWeight?: number;
    stageWeight?: number;
    recencyWeight?: number;
    importanceWeight?: number;
    validityWeight?: number;
  };
  audit?: { enabled?: boolean };
};

export type ResolvedContextIndexConfig = {
  mode: "baseline" | "progressive";
  defaultProjectId?: string;
  recentMessageLimit: number;
  maxSnippetChars: number;
  retrieval: { topK: number; candidateK: number; halfLifeDays: number };
  scoring: {
    keywordWeight: number;
    scopeWeight: number;
    stageWeight: number;
    recencyWeight: number;
    importanceWeight: number;
    validityWeight: number;
  };
  audit: { enabled: boolean };
};

export function resolveContextIndexConfig(
  config: ContextIndexPluginConfig | undefined,
): ResolvedContextIndexConfig {
  return {
    mode: config?.mode ?? "progressive",
    ...(config?.defaultProjectId ? { defaultProjectId: config.defaultProjectId } : {}),
    recentMessageLimit: config?.recentMessageLimit ?? 8,
    maxSnippetChars: config?.maxSnippetChars ?? 900,
    retrieval: {
      topK: config?.retrieval?.topK ?? 8,
      candidateK: config?.retrieval?.candidateK ?? 80,
      halfLifeDays: config?.retrieval?.halfLifeDays ?? 30,
    },
    scoring: {
      keywordWeight: config?.scoring?.keywordWeight ?? 0.35,
      scopeWeight: config?.scoring?.scopeWeight ?? 0.2,
      stageWeight: config?.scoring?.stageWeight ?? 0.15,
      recencyWeight: config?.scoring?.recencyWeight ?? 0.15,
      importanceWeight: config?.scoring?.importanceWeight ?? 0.1,
      validityWeight: config?.scoring?.validityWeight ?? 0.05,
    },
    audit: { enabled: config?.audit?.enabled ?? true },
  };
}

export function stageTypePriority(stage: ContextStage, type: string): number {
  const priorities: Record<ContextStage, readonly string[]> = {
    initial: ["stable_rule", "user_preference", "decision", "task_state", "project_overview"],
    tool_error: ["error", "decision", "task_state", "stable_rule"],
    replan: ["decision", "task_state", "reflection", "error", "stable_rule"],
    tool: ["task_state", "decision", "tool_result", "stable_rule"],
    reflection: ["reflection", "error", "decision", "task_state"],
  };
  const index = priorities[stage].indexOf(type);
  return index === -1 ? 0 : priorities[stage].length - index;
}
