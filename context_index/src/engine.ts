import path from "node:path";
import { delegateCompactionToRuntime } from "openclaw/plugin-sdk/core";
import type { AgentMessage, HarnessContextEngine } from "openclaw/plugin-sdk/agent-harness-runtime";
import { resolveContextIndexConfig, type ContextIndexPluginConfig } from "./config.js";
import { ContextIndexManager } from "./manager.js";
import type { ContextStage, ContextType } from "./types.js";

type ContextIndexEngineOptions = {
  agentDir?: string;
  workspaceDir?: string;
  config?: ContextIndexPluginConfig;
  warn?: (message: string) => void;
  delegateCompaction?: typeof delegateCompactionToRuntime;
};

function messageText(message: AgentMessage): string {
  const content = (message as { content?: unknown }).content;
  if (typeof content === "string") {
    return content;
  }
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .map((part) => {
      if (typeof part === "string") {
        return part;
      }
      if (part && typeof part === "object" && "text" in part && typeof part.text === "string") {
        return part.text;
      }
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

function resolveAgentId(sessionKey: string | undefined): string {
  const match = sessionKey?.match(/^agent:([^:]+)/);
  return match?.[1] ?? "unknown";
}

function detectStage(messages: AgentMessage[]): ContextStage {
  const latest = messageText(messages.at(-1) ?? ({} as AgentMessage)).toLocaleLowerCase();
  if (/(tool error|tool failed|exception|traceback|command failed|\berror\b)/.test(latest)) {
    return "tool_error";
  }
  if (/(replan|re-plan|\u91cd\u65b0\u89c4\u5212|\u91cd\u65b0\u8ba1\u5212|\u6362\u4e00\u79cd\u65b9\u6848)/.test(latest)) {
    return "replan";
  }
  if (/(reflection|reflect|\u590d\u76d8|\u53cd\u601d)/.test(latest)) {
    return "reflection";
  }
  if (/(replan|re-plan|重新规划|重新计划|换一种方案)/.test(latest)) {
    return "replan";
  }
  if (/(reflection|reflect|复盘|反思)/.test(latest)) {
    return "reflection";
  }
  return "initial";
}

function classifyMessage(message: AgentMessage): ContextType {
  const role = (message as { role?: unknown }).role;
  const text = messageText(message).toLocaleLowerCase();
  if (/(tool error|tool failed|exception|traceback|command failed|\berror\b)/.test(text)) {
    return "error";
  }
  if (role === "tool") {
    return "tool_result";
  }
  if (/(decision:|\u51b3\u5b9a\uff1a|\u51b3\u7b56\uff1a|architecture decision)/.test(text)) {
    return "decision";
  }
  if (/(constraint:|\u7ea6\u675f\uff1a|\u5fc5\u987b|must )/.test(text)) {
    return "stable_rule";
  }
  if (/(reflection:|\u53cd\u601d\uff1a|\u590d\u76d8\uff1a)/.test(text)) {
    return "reflection";
  }
  if (/(decision:|决定：|决策：|architecture decision)/.test(text)) {
    return "decision";
  }
  if (/(constraint:|约束：|必须|must )/.test(text)) {
    return "stable_rule";
  }
  if (/(reflection:|反思：|复盘：)/.test(text)) {
    return "reflection";
  }
  return "conversation";
}

function estimateMessagesTokens(messages: AgentMessage[]): number {
  return Math.max(0, Math.ceil(messages.reduce((total, message) => total + messageText(message).length, 0) / 4));
}

export class ContextIndexEngine implements HarnessContextEngine {
  readonly info = {
    id: "context-index",
    name: "Context Index",
    version: "0.1.0",
    ownsCompaction: false,
    hostRequirements: {
      "agent-run": {
        requiredCapabilities: ["assemble-before-prompt" as const],
        unsupportedMessage:
          "Context Index requires an embedded or Codex runtime that assembles context before prompts.",
      },
    },
  };

  readonly #manager: ContextIndexManager;
  readonly #config: ReturnType<typeof resolveContextIndexConfig>;
  readonly #warn?: (message: string) => void;
  readonly #delegateCompaction: typeof delegateCompactionToRuntime;

  constructor(options: ContextIndexEngineOptions) {
    this.#config = resolveContextIndexConfig(options.config);
    const databasePath = path.join(
      options.agentDir ?? options.workspaceDir ?? process.cwd(),
      "context-index.sqlite",
    );
    this.#manager = new ContextIndexManager({ databasePath, config: options.config });
    this.#warn = options.warn;
    this.#delegateCompaction = options.delegateCompaction ?? delegateCompactionToRuntime;
  }

  async ingest(params: Parameters<NonNullable<HarnessContextEngine["ingest"]>>[0]) {
    this.#archiveMessages(params.sessionId, params.sessionKey, [params.message]);
    return { ingested: true };
  }

  async ingestBatch(params: Parameters<NonNullable<HarnessContextEngine["ingestBatch"]>>[0]) {
    const ingestedCount = this.#archiveMessages(params.sessionId, params.sessionKey, params.messages);
    return { ingestedCount };
  }

  async assemble(params: Parameters<HarnessContextEngine["assemble"]>[0]) {
    try {
      // Existing history may predate plugin activation. Index it idempotently before trimming.
      this.#archiveMessages(params.sessionId, params.sessionKey, params.messages);
      const agentId = resolveAgentId(params.sessionKey);
      const projectId = this.#config.defaultProjectId ?? `agent:${agentId}`;
      const stage = detectStage(params.messages);
      const promptQuery = [params.prompt ?? "", messageText(params.messages.at(-1) ?? ({} as AgentMessage))]
        .filter(Boolean)
        .join("\n");
      const tokenBudget = params.tokenBudget ?? 2_000;
      const injection = this.#config.mode === "baseline"
        ? this.#manager.buildBaselineInjection(
            { userQuery: promptQuery, projectId, taskId: params.sessionId, stage },
            tokenBudget,
          )
        : this.#manager.buildInjection(
            { userQuery: promptQuery, projectId, taskId: params.sessionId, stage },
            stage,
            tokenBudget,
          );
      const messages = this.#config.mode === "progressive"
        ? params.messages.slice(-this.#config.recentMessageLimit)
        : params.messages;
      return {
        messages,
        estimatedTokens: estimateMessagesTokens(messages) + injection.estimatedTokens,
        ...(injection.prompt ? { systemPromptAddition: injection.prompt } : {}),
      };
    } catch (error) {
      this.#warn?.(`context-index assemble failed; using unmodified context: ${String(error)}`);
      return { messages: params.messages, estimatedTokens: estimateMessagesTokens(params.messages) };
    }
  }

  async afterTurn(params: Parameters<NonNullable<HarnessContextEngine["afterTurn"]>>[0]): Promise<void> {
    const agentId = resolveAgentId(params.sessionKey);
    this.#archiveMessages(
      params.sessionId,
      params.sessionKey,
      params.messages.slice(params.prePromptMessageCount),
    );
    this.#manager.recordOutcome({
      projectId: this.#config.defaultProjectId ?? `agent:${agentId}`,
      taskId: params.sessionId,
      sessionId: params.sessionId,
      outcome: "completed",
    });
  }

  async compact(params: Parameters<HarnessContextEngine["compact"]>[0]) {
    return await this.#delegateCompaction(params);
  }

  async dispose(): Promise<void> {
    this.#manager.close();
  }

  #archiveMessages(sessionId: string, sessionKey: string | undefined, messages: AgentMessage[]): number {
    const agentId = resolveAgentId(sessionKey);
    const projectId = this.#config.defaultProjectId ?? `agent:${agentId}`;
    let count = 0;
    for (const message of messages) {
      const content = messageText(message).trim();
      if (!content) {
        continue;
      }
      this.#manager.index({
        content,
        type: classifyMessage(message),
        projectId,
        taskId: sessionId,
        source: "session_transcript",
        metadata: { role: (message as { role?: unknown }).role ?? "unknown" },
      });
      count += 1;
    }
    return count;
  }
}
