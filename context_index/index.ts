import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { ContextIndexEngine } from "./src/engine.js";
import { registerContextIndexCli } from "./src/cli.js";
import type { ContextIndexPluginConfig } from "./src/config.js";

export { ContextIndexManager } from "./src/manager.js";
export type * from "./src/types.js";

export default definePluginEntry({
  id: "context-index",
  name: "Context Index",
  description: "Structured progressive-disclosure context assembly for long-running agents.",
  register(api) {
    const config = api.pluginConfig as ContextIndexPluginConfig;
    api.registerContextEngine("context-index", (context) =>
      new ContextIndexEngine({
        agentDir: context.agentDir,
        workspaceDir: context.workspaceDir,
        config,
        warn: (message) => api.logger.warn(message),
      }),
    );
    api.registerCli(
      ({ program }) => {
        registerContextIndexCli(program, config);
      },
      {
        descriptors: [
          {
            name: "context-index",
            description: "Import structured context records and inspect Context Index audit metadata",
            hasSubcommands: true,
          },
        ],
      },
    );
  },
});
