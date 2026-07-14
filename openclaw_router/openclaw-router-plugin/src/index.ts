import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import {
  definePluginEntry,
  type ProviderRuntimeModel,
  type ProviderWrapStreamFnContext,
} from "openclaw/plugin-sdk/plugin-entry";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import { RouterClient, type RouterDecision } from "./router-client.js";

const PROVIDER_ID = "openclaw-router";
const ENV_VAR = "OPENCLAW_ROUTER_API_KEY";

interface RouterPluginConfig {
  endpoint: string;
  apiKey?: string;
  confidenceThreshold: number;
  requestTimeoutMs: number;
  strict: boolean;
  evalSampleId?: string;
  tiers: {
    small: string;
    mid: string;
    large: string;
  };
}

function parsePluginConfig(config: unknown): RouterPluginConfig | null {
  if (typeof config !== "object" || config === null) return null;
  const obj = config as Record<string, unknown>;
  if (typeof obj.endpoint !== "string") return null;
  if (obj.apiKey !== undefined && typeof obj.apiKey !== "string") return null;
  if (typeof obj.tiers !== "object" || obj.tiers === null) return null;
  const tiers = obj.tiers as Record<string, unknown>;
  if (typeof tiers.small !== "string" || typeof tiers.mid !== "string" || typeof tiers.large !== "string") {
    return null;
  }
  const confidenceThreshold = typeof obj.confidenceThreshold === "number" ? obj.confidenceThreshold : 0.5;
  const requestTimeoutMs = typeof obj.requestTimeoutMs === "number" ? obj.requestTimeoutMs : 5000;
  return {
    endpoint: obj.endpoint,
    apiKey: obj.apiKey as string | undefined,
    confidenceThreshold: Math.min(1, Math.max(0, confidenceThreshold)),
    requestTimeoutMs: Math.min(60000, Math.max(100, Math.trunc(requestTimeoutMs))),
    strict: obj.strict === true,
    evalSampleId: typeof obj.evalSampleId === "string" ? obj.evalSampleId : undefined,
    tiers: {
      small: tiers.small,
      mid: tiers.mid,
      large: tiers.large,
    },
  };
}

function pluginConfigFromContext(ctx: ProviderWrapStreamFnContext): unknown {
  const config = ctx.config as
    | { plugins?: { entries?: Record<string, { config?: unknown }> } }
    | undefined;
  return config?.plugins?.entries?.[PROVIDER_ID]?.config;
}

function targetModelFromContext(
  ctx: ProviderWrapStreamFnContext,
  targetModelId: string,
): ProviderRuntimeModel | null {
  const config = ctx.config as
    | {
        models?: {
          providers?: Record<string, { models?: Array<Record<string, unknown>> }>;
        };
      }
    | undefined;
  const target = config?.models?.providers?.[PROVIDER_ID]?.models?.find(
    (candidate) => candidate.id === targetModelId,
  );
  if (!target || !ctx.model) return null;
  return {
    ...ctx.model,
    ...target,
    id: targetModelId,
    provider: ctx.model.provider,
    api: ctx.model.api,
    baseUrl: ctx.model.baseUrl,
  } as ProviderRuntimeModel;
}

function textFromContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (!part || typeof part !== "object") return "";
      const record = part as Record<string, unknown>;
      return typeof record.text === "string" ? record.text : "";
    })
    .filter(Boolean)
    .join("\n");
}

function routeLog(payload: Record<string, unknown>): void {
  console.log(JSON.stringify({ source: "openclaw-router", ...payload }));
}

function createRouterStreamWrapper(
  config: RouterPluginConfig,
  ctx: ProviderWrapStreamFnContext,
): StreamFn | undefined {
  const underlying = ctx.streamFn;
  if (!underlying) return undefined;

  const routerClient = new RouterClient(
    config.endpoint,
    config.apiKey || process.env[ENV_VAR],
    config.requestTimeoutMs,
  );

  return async (model, context, options) => {
    const requestId = randomUUID();
    const startedAt = performance.now();
    try {
      const lastMessage = context.messages[context.messages.length - 1];
      const prompt = textFromContent(lastMessage?.content);

      const decision: RouterDecision = await routerClient.predict(prompt, {
        confidenceThreshold: config.confidenceThreshold,
        evalSampleId: config.evalSampleId,
        requestId,
      });
      const targetModelId = config.tiers[decision.model];

      if (!targetModelId) {
        throw new Error(`No model configured for tier '${decision.model}'`);
      }

      const routedModel = targetModelFromContext(ctx, targetModelId);
      if (!routedModel) {
        throw new Error(`Target model '${targetModelId}' is missing from models.providers.${PROVIDER_ID}.models`);
      }

      routeLog({
        event: "route_decision",
        request_id: requestId,
        eval_sample_id: config.evalSampleId,
        tier: decision.model,
        target_model: targetModelId,
        confidence: decision.confidence,
        routing_mode: decision.routingMode,
        router_latency_ms: Math.round((performance.now() - startedAt) * 1000) / 1000,
      });

      return underlying(routedModel, context, options);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      routeLog({
        event: "route_error",
        request_id: requestId,
        eval_sample_id: config.evalSampleId,
        error: message,
        fallback_model: model.id,
        router_latency_ms: Math.round((performance.now() - startedAt) * 1000) / 1000,
      });
      if (config.strict) {
        throw error;
      }
      return underlying(model, context, options);
    }
  };
}

export default definePluginEntry({
  id: PROVIDER_ID,
  name: "OpenClaw Router",
  description: "Routes LLM requests to small/mid/large models based on external router API",
  register(api) {
    api.registerProvider({
      id: PROVIDER_ID,
      label: "OpenClaw Router",
      envVars: [ENV_VAR],
      wrapStreamFn: (ctx: ProviderWrapStreamFnContext): StreamFn | undefined => {
        const pluginConfig = parsePluginConfig(pluginConfigFromContext(ctx));
        if (!pluginConfig) {
          console.warn("[Router Plugin] Invalid configuration, skipping routing");
          return ctx.streamFn;
        }
        return createRouterStreamWrapper(pluginConfig, ctx);
      },
      wrapSimpleCompletionStreamFn: (ctx: ProviderWrapStreamFnContext): StreamFn | undefined => {
        const pluginConfig = parsePluginConfig(pluginConfigFromContext(ctx));
        if (!pluginConfig) {
          console.warn("[Router Plugin] Invalid configuration, skipping routing");
          return ctx.streamFn;
        }
        return createRouterStreamWrapper(pluginConfig, ctx);
      },
    });
  },
});
