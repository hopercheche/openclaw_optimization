import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import type { AgentMessage, HarnessContextEngine } from "openclaw/plugin-sdk/agent-harness-runtime";
import { ContextIndexEngine } from "../src/engine.js";

function message(role: "user" | "assistant", text: string): AgentMessage {
  return { role, content: [{ type: "text", text }], timestamp: Date.now() } as AgentMessage;
}

test("progressive assembly injects archived evidence and retains only the recent window", async () => {
  const agentDir = mkdtempSync(path.join(os.tmpdir(), "context-index-engine-"));
  const engine = new ContextIndexEngine({
    agentDir,
    config: { defaultProjectId: "project-a", recentMessageLimit: 1 },
  });
  try {
    const first = message("user", "Constraint: the deployment output must be YAML.");
    const toolError = message("assistant", "Tool failed: command failed while generating the deployment file.");
    const assembled = await engine.assemble({
      sessionId: "session-a",
      sessionKey: "agent:main:direct:test",
      messages: [first, toolError],
      tokenBudget: 1_000,
      prompt: "Fix the deployment configuration after the tool error.",
    });
    assert.equal(assembled.messages.length, 1);
    assert.match(assembled.systemPromptAddition ?? "", /deployment output must be YAML/i);
    assert.match(assembled.systemPromptAddition ?? "", /command failed/i);
  } finally {
    await engine.dispose();
    rmSync(agentDir, { recursive: true, force: true });
  }
});

test("baseline preserves the full transcript while progressive trims it", async () => {
  const agentDir = mkdtempSync(path.join(os.tmpdir(), "context-index-engine-"));
  const messages = [message("user", "first"), message("assistant", "second")];
  const baseline = new ContextIndexEngine({
    agentDir,
    config: { defaultProjectId: "project-a", mode: "baseline", recentMessageLimit: 1 },
  });
  try {
    const assembled = await baseline.assemble({
      sessionId: "session-a",
      sessionKey: "agent:main:direct:test",
      messages,
      tokenBudget: 1_000,
      prompt: "continue",
    });
    assert.equal(assembled.messages.length, messages.length);
  } finally {
    await baseline.dispose();
    rmSync(agentDir, { recursive: true, force: true });
  }
});

test("delegates compaction to the OpenClaw runtime bridge", async () => {
  const agentDir = mkdtempSync(path.join(os.tmpdir(), "context-index-engine-"));
  let delegated = false;
  const engine = new ContextIndexEngine({
    agentDir,
    delegateCompaction: async () => {
      delegated = true;
      return { ok: true, compacted: false };
    },
  });
  try {
    const result = await engine.compact({
      sessionId: "session-a",
      sessionFile: path.join(agentDir, "session.jsonl"),
    });
    assert.equal(result.ok, true);
    assert.equal(delegated, true);
  } finally {
    await engine.dispose();
    rmSync(agentDir, { recursive: true, force: true });
  }
});
