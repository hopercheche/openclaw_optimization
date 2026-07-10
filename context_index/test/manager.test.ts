import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ContextIndexManager } from "../src/manager.js";

function withManager(run: (manager: ContextIndexManager) => void): void {
  const directory = mkdtempSync(path.join(os.tmpdir(), "context-index-test-"));
  const manager = new ContextIndexManager({
    databasePath: path.join(directory, "context-index.sqlite"),
    config: { defaultProjectId: "project-a", retrieval: { topK: 20, candidateK: 100 } },
  });
  try {
    run(manager);
  } finally {
    manager.close();
    rmSync(directory, { recursive: true, force: true });
  }
}

test("deduplicates imported content and keeps audit content-free", () => {
  withManager((manager) => {
    const first = manager.index({ content: "Sensitive deployment token is never written to audit.", type: "document" });
    const second = manager.index({ content: "Sensitive deployment token is never written to audit.", type: "document" });
    assert.equal(second.id, first.id);
    assert.ok(manager.listAuditEvents().every((event) => !JSON.stringify(event).includes("Sensitive deployment token")));
  });
});

test("isolates projects and filters requested context types", () => {
  withManager((manager) => {
    manager.index({ content: "Project A architecture decision", type: "decision", projectId: "project-a" });
    manager.index({ content: "Project B architecture decision", type: "decision", projectId: "project-b" });
    manager.index({ content: "Project A chat", type: "conversation", projectId: "project-a" });
    const results = manager.retrieve({
      userQuery: "architecture decision",
      projectId: "project-a",
      stage: "initial",
      contextTypes: ["decision"],
    });
    assert.equal(results.length, 1);
    assert.equal(results[0]?.record.projectId, "project-a");
    assert.equal(results[0]?.record.type, "decision");
  });
});

test("ranks the current task above same-project cross-run distractors", () => {
  withManager((manager) => {
    const target = manager.index({
      content: "The current task requires a YAML configuration file.",
      type: "task_state",
      projectId: "project-a",
      taskId: "target-task",
      importance: 1,
    });
    manager.index({
      content: "An unrelated task also mentions configuration files.",
      type: "task_state",
      projectId: "project-a",
      taskId: "other-task",
      importance: 1,
    });
    const results = manager.retrieve({
      userQuery: "configuration file",
      projectId: "project-a",
      taskId: "target-task",
      stage: "initial",
      maxResults: 1,
    });
    assert.deepEqual(results.map((result) => result.record.id), [target.id]);
  });
});

test("recalls an active project decision from a prior task by default", () => {
  withManager((manager) => {
    const decision = manager.index({
      content: "The project selected SQLite for structured context storage.",
      type: "decision",
      projectId: "project-a",
      taskId: "previous-session",
      importance: 1,
    });
    const results = manager.retrieve({
      userQuery: "which context storage was selected",
      projectId: "project-a",
      taskId: "new-session",
      stage: "replan",
    });
    assert.equal(results[0]?.record.id, decision.id);
  });
});

test("excludes records before validFrom becomes effective", () => {
  withManager((manager) => {
    const now = Date.UTC(2026, 0, 1);
    manager.index({
      content: "Future deployment format switches to TOML.",
      type: "stable_rule",
      projectId: "project-a",
      taskId: "task-1",
      importance: 1,
      validFrom: now + 86_400_000,
    });
    const active = manager.index({
      content: "Current deployment format remains YAML.",
      type: "stable_rule",
      projectId: "project-a",
      taskId: "task-1",
      importance: 0.5,
      validFrom: now - 86_400_000,
    });
    const results = manager.retrieve({
      userQuery: "deployment format",
      projectId: "project-a",
      taskId: "task-1",
      stage: "initial",
      nowMs: now,
    });
    assert.deepEqual(results.map((result) => result.record.id), [active.id]);
  });
});

test("excludes explicitly superseded constraints from progressive retrieval", () => {
  withManager((manager) => {
    const oldRecord = manager.index({
      content: "Output format is JSON.",
      type: "stable_rule",
      taskId: "task-1",
      importance: 1,
    });
    const currentRecord = manager.index({
      content: "Output format is YAML.",
      type: "stable_rule",
      taskId: "task-1",
      importance: 1,
      supersedesId: oldRecord.id,
    });
    const progressive = manager.retrieve({
      userQuery: "current output format",
      projectId: "project-a",
      taskId: "task-1",
      stage: "initial",
    });
    assert.deepEqual(progressive.map((result) => result.record.id), [currentRecord.id]);
    const baseline = manager.buildBaselineInjection(
      { userQuery: "current output format", projectId: "project-a", taskId: "task-1", stage: "initial" },
      1_000,
    );
    assert.ok(baseline.selected.some((result) => result.record.id === oldRecord.id));
  });
});

test("applies explicit supersede when duplicate replacement content already exists", () => {
  withManager((manager) => {
    const oldRecord = manager.index({
      content: "Retry scenario output format is JSON.",
      type: "stable_rule",
      taskId: "task-1",
      importance: 1,
    });
    const existingReplacement = manager.index({
      content: "Retry scenario output format is YAML.",
      type: "stable_rule",
      taskId: "task-1",
      importance: 1,
    });
    const retry = manager.index({
      content: "Retry scenario output format is YAML.",
      type: "stable_rule",
      taskId: "task-1",
      importance: 1,
      supersedesId: oldRecord.id,
    });
    assert.equal(retry.id, existingReplacement.id);
    const progressive = manager.retrieve({
      userQuery: "retry scenario output format",
      projectId: "project-a",
      taskId: "task-1",
      stage: "initial",
    });
    assert.deepEqual(progressive.map((result) => result.record.id), [existingReplacement.id]);
  });
});

test("rejects invalid supersedes imports without indexing the replacement", () => {
  withManager((manager) => {
    assert.throws(
      () =>
        manager.index({
          content: "Invalid replacement should not become active.",
          type: "stable_rule",
          taskId: "task-1",
          supersedesId: "missing-context-id",
        }),
      /Superseded context record must exist/,
    );
    const results = manager.retrieve({
      userQuery: "invalid replacement active",
      projectId: "project-a",
      taskId: "task-1",
      stage: "initial",
    });
    assert.deepEqual(results, []);
  });
});

test("prioritizes a new high-importance decision and observes token budgets", () => {
  withManager((manager) => {
    manager.index({
      content: "Old normal conversation about deployment.",
      type: "conversation",
      taskId: "task-1",
      importance: 0.1,
      createdAt: Date.UTC(2020, 0, 1),
    });
    const decision = manager.index({
      content: "Current production deployment requires a staged rollout.",
      type: "decision",
      taskId: "task-1",
      importance: 1,
      createdAt: Date.UTC(2026, 0, 1),
    });
    const injection = manager.buildInjection(
      { userQuery: "production deployment", projectId: "project-a", taskId: "task-1", stage: "replan" },
      "replan",
      40,
    );
    assert.ok(injection.selected.some((result) => result.record.id === decision.id));
    assert.ok(injection.estimatedTokens <= 40);
  });
});
