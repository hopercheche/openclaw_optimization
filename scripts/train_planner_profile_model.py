from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openclaw.planner_profile_model import (  # noqa: E402
    DEFAULT_MODEL_PATH,
    PlannerProfileExample,
    evaluate_profile_model,
    save_profile_model,
    train_profile_model,
)
from scripts.build_planner_generalization_suite import build_tasks  # noqa: E402


DEFAULT_METRICS_OUTPUT = PROJECT_ROOT / "data" / "planner_models" / "profile_policy_metrics.json"
DEFAULT_REPORT_OUTPUT = PROJECT_ROOT / "data" / "planner_models" / "profile_policy_report.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a lightweight planner profile policy model from local planner datasets.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    parser.add_argument("--phoneharness-limit", type=int, default=1000)
    parser.add_argument("--tau2-per-domain", type=int, default=1000)
    parser.add_argument("--toolbench-limit", type=int, default=1000)
    parser.add_argument("--skillsbench-limit", type=int, default=1000)
    parser.add_argument(
        "--suite",
        type=Path,
        action="append",
        default=[],
        help="Add OpenClaw planner benchmark suite JSON files as training examples.",
    )
    parser.add_argument(
        "--no-default-generalization",
        action="store_true",
        help="Use only --suite and optional terminal templates, skipping built-in external dataset conversion.",
    )
    parser.add_argument(
        "--final-train-split",
        choices=["all", "dev"],
        default="all",
        help="Choose whether the saved model is trained on all examples or dev examples only.",
    )
    parser.add_argument(
        "--include-terminal-templates",
        action="store_true",
        help="Add synthetic terminal-command profile examples that do not copy benchmark task text.",
    )
    parser.add_argument("--terminal-template-repeats", type=int, default=1)
    parser.add_argument("--balanced-prior", action="store_true")
    parser.add_argument(
        "--keep-profile-hints",
        action="store_true",
        help="Train on raw goals including explicit bracket hints. Default strips them to test semantic generalization.",
    )
    args = parser.parse_args()

    tasks = [] if args.no_default_generalization else build_tasks(
        phoneharness_limit=args.phoneharness_limit,
        tau2_per_domain=args.tau2_per_domain,
        toolbench_limit=args.toolbench_limit,
        skillsbench_limit=args.skillsbench_limit,
    )
    for suite_path in args.suite:
        tasks.extend(_load_suite_tasks(suite_path))
    examples = [_example_from_task(task) for task in tasks if _has_training_labels(task)]
    if args.include_terminal_templates:
        terminal_examples = _terminal_template_examples()
        for _ in range(max(1, args.terminal_template_repeats)):
            examples.extend(terminal_examples)
    if not examples:
        raise SystemExit("No trainable planner profile examples found")

    strip_hints = not args.keep_profile_hints
    dev_examples = [example for example in examples if example.split != "holdout"]
    holdout_examples = [example for example in examples if example.split == "holdout"]

    eval_model = train_profile_model(
        dev_examples or examples,
        strip_hints=strip_hints,
        balanced_prior=args.balanced_prior,
    )
    holdout_metrics = evaluate_profile_model(eval_model, holdout_examples, strip_hints=strip_hints)
    dev_metrics = evaluate_profile_model(eval_model, dev_examples, strip_hints=strip_hints)

    final_examples = dev_examples if args.final_train_split == "dev" else examples
    if not final_examples:
        final_examples = examples
    final_model = train_profile_model(
        final_examples,
        strip_hints=strip_hints,
        balanced_prior=args.balanced_prior,
    )
    final_model["training_summary"] = {
        "source_counts": _counts(examples, "source_family"),
        "profile_counts": _counts(examples, "planner_profile"),
        "policy_counts": _counts(examples, "policy_mode"),
        "tool_counts": _tool_counts(examples),
        "split_counts": _counts(examples, "split"),
        "strip_profile_hints": strip_hints,
        "balanced_prior": args.balanced_prior,
        "terminal_template_repeats": max(1, args.terminal_template_repeats) if args.include_terminal_templates else 0,
        "final_train_split": args.final_train_split,
        "final_example_count": len(final_examples),
    }
    final_model["evaluation"] = {
        "dev": dev_metrics,
        "holdout": holdout_metrics,
    }
    save_profile_model(final_model, args.output)

    metrics = {
        "model_path": str(args.output),
        "example_count": len(examples),
        "dev_count": len(dev_examples),
        "holdout_count": len(holdout_examples),
        "strip_profile_hints": strip_hints,
        "balanced_prior": args.balanced_prior,
        "terminal_template_repeats": max(1, args.terminal_template_repeats) if args.include_terminal_templates else 0,
        "final_train_split": args.final_train_split,
        "final_example_count": len(final_examples),
        "dev": dev_metrics,
        "holdout": holdout_metrics,
        "training_summary": final_model["training_summary"],
    }
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(_render_report(metrics), encoding="utf-8")
    print(json.dumps({
        "model_path": str(args.output),
        "metrics_output": str(args.metrics_output),
        "report_output": str(args.report_output),
        "example_count": len(examples),
        "dev_count": len(dev_examples),
        "holdout_count": len(holdout_examples),
        "final_train_split": args.final_train_split,
        "final_example_count": len(final_examples),
        "holdout": {
            "planner_profile_accuracy": holdout_metrics["planner_profile_accuracy"],
            "execution_tools_accuracy": holdout_metrics["execution_tools_accuracy"],
            "policy_mode_accuracy": holdout_metrics["policy_mode_accuracy"],
        },
    }, ensure_ascii=False, indent=2))


def _has_training_labels(task: dict[str, Any]) -> bool:
    return bool(task.get("planner_profile")) and bool(task.get("profile_execution_tools"))


def _load_suite_tasks(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("tasks", "cases", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise SystemExit(f"Unsupported suite shape: {path}")


def _example_from_task(task: dict[str, Any]) -> PlannerProfileExample:
    return PlannerProfileExample(
        goal=str(task.get("goal", "")),
        planner_profile=str(task.get("planner_profile", "")),
        execution_tools=[str(tool) for tool in task.get("profile_execution_tools", [])],
        policy_mode=str(task.get("profile_policy_mode", "act")),
        source_family=str(task.get("source_family", "")),
        split=str(task.get("split", "dev")),
    )


def _terminal_template_examples() -> list[PlannerProfileExample]:
    act_templates = [
        "TerminalWorld verified terminal task. Plan a safe, auditable terminal execution path and save the required output artifact.",
        "TerminalWorld style CLI task: execute the relevant command-line workflow and preserve all command output.",
        "Verified terminal benchmark task requiring a command runner, shell execution, and an output file under /app.",
        "Run a terminal command and save its stdout and stderr into the requested result file.",
        "Use a shell pipeline to transform a local text file and write the final answer to /app/result.txt.",
        "Inspect a project from the command line, execute the relevant validation command, and capture logs.",
        "Use git commands to inspect repository state and produce a concise terminal-based report.",
        "Run a Python script from the terminal to process CSV data and save the generated output artifact.",
        "Use awk, sed, sort, and uniq in a shell pipeline to compute the requested summary file.",
        "Execute a container CLI command in a bounded workspace and preserve the diagnostic output.",
        "Query a local SQLite database from the command line and write the selected rows to a file.",
        "Run pytest for the specified package and save the complete command output for audit review.",
        "Use curl against a local service endpoint and store the response body in the requested output path.",
        "Create a small shell script that performs the requested local filesystem transformation.",
        "Compress selected files with tar from the command line and save the archive in the workspace.",
        "Run a package manager inspection command and capture version or dependency information.",
        "Use command-line image or media tooling to convert an input artifact to the requested format.",
        "Launch a local dummy service from the terminal and write all launch diagnostics to a result file.",
    ]
    confirm_templates = [
        "TerminalWorld security terminal task. Plan command execution with explicit confirmation before sudo, SSH, credential, or authentication steps.",
        "Verified terminal benchmark task with privileged shell execution, requiring human confirmation before command_runner.",
        "Run a sudo command over SSH and save the output, but require confirmation before privileged execution.",
        "Use SSH port forwarding to reach a local service and execute a sensitive terminal command.",
        "Handle a credential or smart-card authenticated terminal workflow with explicit approval gating.",
        "Run a security-oriented command-line task that touches authentication material and must be human gated.",
        "Execute a terminal command involving tokens or secrets, recording the permission decision before running.",
    ]
    examples: list[PlannerProfileExample] = []
    for index, text in enumerate(act_templates, start=1):
        examples.append(PlannerProfileExample(
            goal=f"Terminal CLI workflow template {index}: {text}",
            planner_profile="terminal_cli_workflow",
            execution_tools=["command_runner"],
            policy_mode="act",
            source_family="terminal_template",
            split="dev",
        ))
    for index, text in enumerate(confirm_templates, start=1):
        examples.append(PlannerProfileExample(
            goal=f"Terminal privileged workflow template {index}: {text}",
            planner_profile="terminal_cli_workflow",
            execution_tools=["command_runner"],
            policy_mode="confirm",
            source_family="terminal_template",
            split="dev",
        ))
    return examples


def _counts(examples: list[PlannerProfileExample], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for example in examples:
        value = str(getattr(example, field))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _tool_counts(examples: list[PlannerProfileExample]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for example in examples:
        for tool in example.execution_tools:
            counts[tool] = counts.get(tool, 0) + 1
    return dict(sorted(counts.items()))


def _render_report(metrics: dict[str, Any]) -> str:
    holdout = metrics["holdout"]
    dev = metrics["dev"]
    summary = metrics["training_summary"]
    return "\n".join([
        "# Planner Profile Model Report",
        "",
        f"- Model path: `{metrics['model_path']}`",
        f"- Examples: {metrics['example_count']} ({metrics['dev_count']} dev, {metrics['holdout_count']} holdout)",
        f"- Profile hints stripped during training/eval: {metrics['strip_profile_hints']}",
        f"- Balanced class prior: {metrics['balanced_prior']}",
        f"- Terminal template repeats: {metrics['terminal_template_repeats']}",
        "",
        "## Holdout Accuracy",
        "",
        f"- Planner profile: {holdout['planner_profile_accuracy']:.2%}",
        f"- Execution tools: {holdout['execution_tools_accuracy']:.2%}",
        f"- Policy mode: {holdout['policy_mode_accuracy']:.2%}",
        "",
        "## Dev Accuracy",
        "",
        f"- Planner profile: {dev['planner_profile_accuracy']:.2%}",
        f"- Execution tools: {dev['execution_tools_accuracy']:.2%}",
        f"- Policy mode: {dev['policy_mode_accuracy']:.2%}",
        "",
        "## Training Distribution",
        "",
        f"- Sources: `{json.dumps(summary['source_counts'], ensure_ascii=False)}`",
        f"- Profiles: `{json.dumps(summary['profile_counts'], ensure_ascii=False)}`",
        f"- Policies: `{json.dumps(summary['policy_counts'], ensure_ascii=False)}`",
        f"- Tools: `{json.dumps(summary['tool_counts'], ensure_ascii=False)}`",
        "",
        "## Method",
        "",
        "The model is a standard-library multinomial Naive Bayes classifier trained on local multi-source planner fixtures. "
        "It learns three supervised labels from the datasets: planner profile, execution-tool set, and policy mode. "
        "OpenClaw uses the model only as a conservative hint when explicit `execution_tool(s)=...` metadata is absent.",
        "",
    ])


if __name__ == "__main__":
    main()
