import { definePluginEntry, type ProviderWrapStreamFnContext } from "openclaw/plugin-sdk/plugin-entry";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import { RouterClient, type RouterDecision } from "./router-client.js";

const PROVIDER_ID = "openclaw-router";
const ENV_VAR = "OPENCLAW_ROUTER_API_KEY";

interface RouterPluginConfig {
  endpoint: string;
  apiKey?: string;
  models: {
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
  if (typeof obj.models !== "object" || obj.models === null) return null;
  const models = obj.models as Record<string, unknown>;
  if (typeof models.small !== "string" || typeof models.mid !== "string" || typeof models.large !== "string") {
    return null;
  }
  return {
    endpoint: obj.endpoint,
    apiKey: obj.apiKey as string | undefined,
    models: {
      small: models.small,
      mid: models.mid,
      large: models.large,
    },
  };
}

function createRouterStreamWrapper(
  config: RouterPluginConfig,
  underlying: StreamFn | undefined,
): StreamFn | undefined {
  if (!underlying) return undefined;

  const routerClient = new RouterClient(config.endpoint, config.apiKey);

  return async (model, context, options) => {
    try {
      const lastMessage = context.messages[context.messages.length - 1];
      const prompt = typeof lastMessage?.content === "string" ? lastMessage.content : "";

      const decision: RouterDecision = await routerClient.predict(prompt);
      const targetModelId = config.models[decision.model];

      if (!targetModelId) {
        console.warn(`[Router Plugin] No model configured for tier '${decision.model}'`);
        return underlying(model, context, options);
      }

      console.log(`[Router Plugin] Routing to ${decision.model}: ${targetModelId}`);

      const routedModel = {
        ...model,
        id: targetModelId,
      };

      return underlying(routedModel, context, options);
    } catch (error) {
      console.error(`[Router Plugin] Routing failed, falling back: ${error instanceof Error ? error.message : String(error)}`);
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
        const pluginConfig = parsePluginConfig(ctx.providerConfig);
        if (!pluginConfig) {
          console.warn("[Router Plugin] Invalid configuration, skipping routing");
          return ctx.streamFn;
        }
        return createRouterStreamWrapper(pluginConfig, ctx.streamFn);
      },
      wrapSimpleCompletionStreamFn: (ctx: ProviderWrapStreamFnContext): StreamFn | undefined => {
        const pluginConfig = parsePluginConfig(ctx.providerConfig);
        if (!pluginConfig) {
          console.warn("[Router Plugin] Invalid configuration, skipping routing");
          return ctx.streamFn;
        }
        return createRouterStreamWrapper(pluginConfig, ctx.streamFn);
      },
    });
  },
});