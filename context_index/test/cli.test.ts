import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { Command } from "commander";
import { registerContextIndexCli } from "../src/cli.js";
import { ContextIndexManager } from "../src/manager.js";

test("CLI imports a UTF-8 Markdown document into the agent index", async () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "context-index-cli-"));
  const sourcePath = path.join(directory, "requirements.md");
  writeFileSync(sourcePath, "The deployed configuration must use YAML.\n", "utf8");
  const program = new Command();
  program.exitOverride();
  registerContextIndexCli(program);
  try {
    await program.parseAsync([
      "node",
      "context-index",
      "context-index",
      "import",
      sourcePath,
      "--project",
      "project-a",
      "--task",
      "task-a",
      "--agent-dir",
      directory,
      "--type",
      "document",
    ]);
    const manager = new ContextIndexManager({ databasePath: path.join(directory, "context-index.sqlite") });
    try {
      const results = manager.retrieve({
        userQuery: "deployed configuration YAML",
        projectId: "project-a",
        taskId: "task-a",
        stage: "initial",
      });
      assert.equal(results.length, 1);
      assert.match(results[0]?.record.content ?? "", /YAML/);
    } finally {
      manager.close();
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
