import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { Command } from "commander";
import type { ContextIndexPluginConfig } from "./config.js";
import { ContextIndexManager } from "./manager.js";
import { CONTEXT_TYPES, type ContextType } from "./types.js";

function defaultDatabasePath(agentDir?: string): string {
  return path.join(agentDir ?? path.join(os.homedir(), ".openclaw", "agents", "main", "agent"), "context-index.sqlite");
}

function parseContextType(value: string): ContextType {
  if ((CONTEXT_TYPES as readonly string[]).includes(value)) {
    return value as ContextType;
  }
  throw new Error(`--type must be one of: ${CONTEXT_TYPES.join(", ")}`);
}

function parseImportance(value: string): number {
  const result = Number(value);
  if (!Number.isFinite(result) || result < 0 || result > 1) {
    throw new Error("--importance must be a number from 0 to 1.");
  }
  return result;
}

export function registerContextIndexCli(program: Command, config?: ContextIndexPluginConfig): void {
  const root = program.command("context-index").description("Manage structured Context Index records");
  root
    .command("import")
    .description("Import a UTF-8 .md, .txt, or .json file as an explicit context record")
    .argument("<path>", "Path to the UTF-8 source file")
    .requiredOption("--project <id>", "Project id")
    .option("--task <id>", "Task id")
    .option("--type <type>", `Context type (${CONTEXT_TYPES.join(", ")})`, parseContextType, "document")
    .option("--importance <n>", "Importance from 0 to 1", parseImportance, 0.7)
    .option("--supersedes <context-id>", "Explicit context record replaced by this import")
    .option("--agent-dir <path>", "Agent directory containing context-index.sqlite")
    .option("--json", "Print JSON")
    .action(async (inputPath: string, options) => {
      const extension = path.extname(inputPath).toLocaleLowerCase();
      if (![".md", ".txt", ".json"].includes(extension)) {
        throw new Error("Only UTF-8 .md, .txt, and .json imports are supported by the MVP.");
      }
      const manager = new ContextIndexManager({ databasePath: defaultDatabasePath(options.agentDir), config });
      try {
        const content = await fs.readFile(inputPath, "utf8");
        const record = manager.index({
          content,
          type: options.type,
          projectId: options.project,
          taskId: options.task,
          importance: options.importance,
          source: "cli_import",
          sourceRef: path.resolve(inputPath),
          ...(options.supersedes ? { supersedesId: options.supersedes } : {}),
        });
        process.stdout.write(`${options.json ? JSON.stringify(record, null, 2) : `Imported ${record.id} (${record.type})`}\n`);
      } finally {
        manager.close();
      }
    });

  root
    .command("audit")
    .description("Show context audit metadata without source content")
    .option("--limit <n>", "Maximum events", (value: string) => Number.parseInt(value, 10), 50)
    .option("--agent-dir <path>", "Agent directory containing context-index.sqlite")
    .option("--json", "Print JSON")
    .action((options) => {
      const manager = new ContextIndexManager({ databasePath: defaultDatabasePath(options.agentDir), config });
      try {
        const events = manager.listAuditEvents(options.limit);
        process.stdout.write(`${JSON.stringify(events, null, options.json ? 2 : 0)}\n`);
      } finally {
        manager.close();
      }
    });
}
