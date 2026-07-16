import { chmod, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

const stateDir = process.env.OPENCLAW_STATE_DIR || "/home/node/.openclaw";
const configPath =
  process.env.OPENCLAW_CONFIG_PATH || path.join(stateDir, "openclaw.json");
const workspacePath =
  process.env.OPENCLAW_WORKSPACE_DIR || path.join(stateDir, "workspace");

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function integer(name, fallback, minimum = 1) {
  const raw = process.env[name]?.trim();
  const value = raw ? Number.parseInt(raw, 10) : fallback;
  if (!Number.isInteger(value) || value < minimum) {
    throw new Error(`${name} must be an integer >= ${minimum}`);
  }
  return value;
}

function number(name, fallback, minimum, maximum) {
  const raw = process.env[name]?.trim();
  const value = raw ? Number(raw) : fallback;
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}`);
  }
  return value;
}

function boolean(name, fallback) {
  const raw = process.env[name]?.trim().toLowerCase();
  if (!raw) {
    return fallback;
  }
  if (["1", "true", "yes", "on"].includes(raw)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(raw)) {
    return false;
  }
  throw new Error(`${name} must be true or false`);
}

function normalizedOrigin(raw) {
  const url = new URL(raw);
  const allowHttp = boolean("OPENCLAW_DEMO_ALLOW_HTTP", false);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("OPENCLAW_DEMO_PUBLIC_ORIGIN must use http:// or https://");
  }
  if (url.protocol === "http:" && !allowHttp) {
    throw new Error(
      "HTTP origin is disabled by default; set OPENCLAW_DEMO_ALLOW_HTTP=true for an explicitly insecure public demo",
    );
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("OPENCLAW_DEMO_PUBLIC_ORIGIN must be a bare HTTPS origin");
  }
  if (url.pathname !== "/") {
    throw new Error("OPENCLAW_DEMO_PUBLIC_ORIGIN must not include a path");
  }
  return url.origin;
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function deepMerge(base, override) {
  if (!isPlainObject(base) || !isPlainObject(override)) {
    return override;
  }
  const merged = { ...base };
  for (const [key, value] of Object.entries(override)) {
    merged[key] = isPlainObject(value)
      ? deepMerge(isPlainObject(merged[key]) ? merged[key] : {}, value)
      : value;
  }
  return merged;
}

async function readExistingConfig() {
  try {
    const source = await readFile(configPath, "utf8");
    const parsed = JSON.parse(source);
    if (!isPlainObject(parsed)) {
      throw new Error("existing OpenClaw config is not a JSON object");
    }
    return parsed;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return {};
    }
    throw error;
  }
}

const publicOrigin = normalizedOrigin(required("OPENCLAW_DEMO_PUBLIC_ORIGIN"));
const modelBaseUrl = required("OPENCLAW_DEMO_MODEL_API_URL").replace(/\/+$/, "");
const modelApi = process.env.OPENCLAW_DEMO_MODEL_API?.trim() || "openai-responses";
const smallModel = required("OPENCLAW_DEMO_SMALL_MODEL");
const midModel = required("OPENCLAW_DEMO_MID_MODEL");
const largeModel = required("OPENCLAW_DEMO_LARGE_MODEL");
const contextWindow = integer("OPENCLAW_DEMO_CONTEXT_WINDOW", 131072, 1024);
const maxTokens = integer("OPENCLAW_DEMO_MAX_TOKENS", 8192, 1);
const routerThreshold = number(
  "OPENCLAW_DEMO_ROUTER_CONFIDENCE_THRESHOLD",
  0.5,
  0,
  1,
);
const routerTimeoutMs = integer("OPENCLAW_DEMO_ROUTER_TIMEOUT_MS", 5000, 100);
const routerStrict = boolean("OPENCLAW_DEMO_ROUTER_STRICT", true);

const modelIds = ["router-entry", smallModel, midModel, largeModel].filter(
  (modelId, index, values) => values.indexOf(modelId) === index,
);
const modelEntries = modelIds.map((modelId) => ({
  id: modelId,
  name: modelId === "router-entry" ? "OpenClaw Router Entry" : modelId,
  reasoning: modelId !== smallModel,
  input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow,
  contextTokens: contextWindow,
  maxTokens,
}));
const agentModels = Object.fromEntries(
  modelIds.map((modelId) => [`openclaw-router/${modelId}`, {}]),
);

const managedConfig = {
  gateway: {
    mode: "local",
    bind: "lan",
    auth: {
      mode: "token",
      allowTailscale: false,
    },
    controlUi: {
      enabled: true,
      allowedOrigins: [publicOrigin],
      allowInsecureAuth: false,
      dangerouslyDisableDeviceAuth: true,
      dangerouslyAllowHostHeaderOriginFallback: false,
    },
    terminal: {
      enabled: false,
    },
  },
  models: {
    mode: "merge",
    pricing: { enabled: false },
    providers: {
      "openclaw-router": {
        baseUrl: modelBaseUrl,
        apiKey: {
          source: "env",
          provider: "default",
          id: "OPENCLAW_DEMO_MODEL_API_KEY",
        },
        api: modelApi,
        models: modelEntries,
      },
    },
  },
  agents: {
    defaults: {
      workspace: workspacePath,
      model: { primary: "openclaw-router/router-entry" },
      models: agentModels,
      timeoutSeconds: integer("OPENCLAW_DEMO_AGENT_TIMEOUT", 600, 1),
    },
  },
  tools: {
    profile: process.env.OPENCLAW_DEMO_TOOL_PROFILE?.trim() || "minimal",
  },
  plugins: {
    load: {
      paths: [
        "/opt/openclaw-plugins/openclaw-router",
        "/opt/openclaw-plugins/context-index",
        "/opt/openclaw-plugins/task-compass",
      ],
    },
    allow: ["openclaw-router", "context-index", "task-compass"],
    slots: {
      contextEngine: "context-index",
    },
    entries: {
      "openclaw-router": {
        enabled: true,
        config: {
          endpoint: "http://openclaw-router-api:3000",
          confidenceThreshold: routerThreshold,
          requestTimeoutMs: routerTimeoutMs,
          strict: routerStrict,
          tiers: {
            small: smallModel,
            mid: midModel,
            large: largeModel,
          },
        },
      },
      "context-index": {
        enabled: true,
        config: {
          mode: process.env.OPENCLAW_DEMO_CONTEXT_INDEX_MODE?.trim() || "progressive",
          defaultProjectId:
            process.env.OPENCLAW_DEMO_CONTEXT_INDEX_PROJECT_ID?.trim() || "public-demo",
          recentMessageLimit: integer(
            "OPENCLAW_DEMO_CONTEXT_INDEX_RECENT_MESSAGE_LIMIT",
            8,
            1,
          ),
          maxSnippetChars: integer(
            "OPENCLAW_DEMO_CONTEXT_INDEX_MAX_SNIPPET_CHARS",
            900,
            80,
          ),
          retrieval: {
            topK: integer("OPENCLAW_DEMO_CONTEXT_INDEX_TOP_K", 8, 1),
            candidateK: integer("OPENCLAW_DEMO_CONTEXT_INDEX_CANDIDATE_K", 80, 1),
            halfLifeDays: number(
              "OPENCLAW_DEMO_CONTEXT_INDEX_HALF_LIFE_DAYS",
              30,
              Number.MIN_VALUE,
              Number.MAX_VALUE,
            ),
          },
          scoring: {
            keywordWeight: 0.35,
            scopeWeight: 0.2,
            stageWeight: 0.15,
            recencyWeight: 0.15,
            importanceWeight: 0.1,
            validityWeight: 0.05,
          },
          audit: { enabled: true },
        },
      },
      "task-compass": {
        enabled: true,
        config: {
          enabled: true,
          pythonBin: "python3",
          timeoutMs: integer("OPENCLAW_DEMO_PLANNER_TIMEOUT_MS", 1500, 100),
          maxPromptChars: integer("OPENCLAW_DEMO_PLANNER_MAX_PROMPT_CHARS", 12000, 256),
        },
      },
    },
  },
};

await mkdir(stateDir, { recursive: true });
await mkdir(workspacePath, { recursive: true });

const config = deepMerge(await readExistingConfig(), managedConfig);
const temporaryPath = `${configPath}.tmp-${process.pid}`;
await writeFile(temporaryPath, `${JSON.stringify(config, null, 2)}\n`, {
  mode: 0o600,
});
await chmod(temporaryPath, 0o600);
await rename(temporaryPath, configPath);

console.log(
  JSON.stringify({
    event: "openclaw_demo_initialized",
    configPath,
    workspacePath,
    publicOrigin,
    provider: "openclaw-router",
    models: { small: smallModel, mid: midModel, large: largeModel },
    plugins: ["openclaw-router", "context-index", "task-compass"],
  }),
);
