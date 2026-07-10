import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";
import { ContextIndexManager } from "./manager.js";

type ModeMetrics = {
  task_accuracy: number;
  constraint_follow_rate: number;
  outdated_context_error_rate: number;
  context_precision: number;
  context_recall_at_k: number;
  injected_token_count: number;
  total_prompt_tokens: number;
  retrieval_latency: number;
  context_drift_rate: number;
};

function parseOutputDirectory(): string {
  const index = process.argv.indexOf("--out-dir");
  return index >= 0 && process.argv[index + 1]
    ? path.resolve(process.argv[index + 1]!)
    : path.resolve("artifacts");
}

function calculateMetrics(params: {
  prompt: string;
  selectedIds: string[];
  yamlId: string;
  jsonId: string;
  latencyMs: number;
  tokens: number;
}): ModeMetrics {
  const hasCurrent = params.selectedIds.includes(params.yamlId);
  const hasOutdated = params.selectedIds.includes(params.jsonId);
  const relevantSelected = hasCurrent ? 1 : 0;
  const precision = params.selectedIds.length === 0 ? 0 : relevantSelected / params.selectedIds.length;
  const isCorrect = hasCurrent && !hasOutdated && params.prompt.includes("YAML");
  return {
    task_accuracy: Number(isCorrect),
    constraint_follow_rate: Number(hasCurrent && !hasOutdated),
    outdated_context_error_rate: Number(hasOutdated),
    context_precision: precision,
    context_recall_at_k: Number(hasCurrent),
    injected_token_count: params.tokens,
    total_prompt_tokens: params.tokens,
    retrieval_latency: params.latencyMs,
    context_drift_rate: Number(hasOutdated),
  };
}

export function runContextIndexBenchmark(outputDir = parseOutputDirectory()): {
  baseline: ModeMetrics;
  progressive: ModeMetrics;
} {
  const tempDir = mkdtempSync(path.join(os.tmpdir(), "context-index-benchmark-"));
  const manager = new ContextIndexManager({
    databasePath: path.join(tempDir, "context-index.sqlite"),
    config: { defaultProjectId: "benchmark-project", retrieval: { topK: 40, candidateK: 100 } },
  });
  try {
    const oldConstraint = manager.index({
      content: "Output format must be JSON.",
      type: "stable_rule",
      projectId: "benchmark-project",
      taskId: "configuration",
      importance: 1,
      source: "benchmark",
      createdAt: Date.UTC(2026, 0, 1),
    });
    const currentConstraint = manager.index({
      content: "Output format changed to YAML.",
      type: "stable_rule",
      projectId: "benchmark-project",
      taskId: "configuration",
      importance: 1,
      source: "benchmark",
      createdAt: Date.UTC(2026, 0, 10),
      supersedesId: oldConstraint.id,
    });
    for (let index = 0; index < 30; index += 1) {
      manager.index({
        content: `Distractor project note ${index}: unrelated deployment discussion.`,
        type: "conversation",
        projectId: "benchmark-project",
        taskId: `distractor-${index}`,
        importance: 0.1,
        source: "benchmark",
      });
    }
    const query = {
      userQuery: "Generate the final configuration file using the current output format.",
      projectId: "benchmark-project",
      taskId: "configuration",
      stage: "initial" as const,
      contextTypes: ["stable_rule" as const],
    };
    const baselineStartedAt = performance.now();
    const baseline = manager.buildBaselineInjection(query, 20_000);
    const baselineLatency = performance.now() - baselineStartedAt;
    const progressiveStartedAt = performance.now();
    const progressive = manager.buildInjection(query, "initial", 1_200);
    const progressiveLatency = performance.now() - progressiveStartedAt;
    const result = {
      evaluation_name: "direction2_context_index_deterministic_benchmark",
      disclaimer: "Retrieval and injection oracle only; this does not measure model end-to-end quality.",
      baseline: calculateMetrics({
        prompt: baseline.prompt,
        selectedIds: baseline.selected.map((item) => item.record.id),
        yamlId: currentConstraint.id,
        jsonId: oldConstraint.id,
        latencyMs: baselineLatency,
        tokens: baseline.estimatedTokens,
      }),
      progressive: calculateMetrics({
        prompt: progressive.prompt,
        selectedIds: progressive.selected.map((item) => item.record.id),
        yamlId: currentConstraint.id,
        jsonId: oldConstraint.id,
        latencyMs: progressiveLatency,
        tokens: progressive.estimatedTokens,
      }),
    };
    mkdirSync(outputDir, { recursive: true });
    writeFileSync(path.join(outputDir, "context-index-benchmark.json"), JSON.stringify(result, null, 2));
    writeFileSync(
      path.join(outputDir, "context-index-benchmark.md"),
      [
        "# Context Index deterministic benchmark",
        "",
        result.disclaimer,
        "",
        "| Metric | Baseline | Progressive |",
        "| --- | ---: | ---: |",
        ...Object.keys(result.baseline).map(
          (metric) =>
            `| ${metric} | ${result.baseline[metric as keyof ModeMetrics]} | ${result.progressive[metric as keyof ModeMetrics]} |`,
        ),
      ].join("\n"),
    );
    return { baseline: result.baseline, progressive: result.progressive };
  } finally {
    manager.close();
    rmSync(tempDir, { recursive: true, force: true });
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const result = runContextIndexBenchmark();
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}
