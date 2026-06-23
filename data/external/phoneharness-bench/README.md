---
pretty_name: PhoneHarness Bench
license: apache-2.0
tags:
- phone-agent
- mobile-agent
- benchmark
- android
- cli
- gui
- mcp
- verifier
configs:
- config_name: main_tasks
  data_files:
  - split: train
    path: data/main_tasks.jsonl
- config_name: safety_tasks
  data_files:
  - split: train
    path: data/safety_tasks.jsonl
---

# PhoneHarness Bench

PhoneHarness Bench is a benchmark for evaluating phone agents on verifiable mixed-action mobile workflows. It is built around the PhoneHarness orchestration harness, where agents may operate through Android app GUI interaction, device-side command execution, Python/ADB utilities, and host-side MCP-style tools.

Project homepage: https://phoneharness.github.io/

## Dataset Scope

This release contains task definitions and verifier metadata only. It does not include execution traces, model completions, screenshots, private run logs, or temporary rerun artifacts.

- **Main tasks:** 124 mixed-action phone tasks from the `120tasks30apps` release.
- **Safety tasks:** 30 safety-oriented tasks from `safety_bench`.
- **Total examples:** 154.

## Files

- `data/main_tasks.jsonl`: 124 main task records with prompt, difficulty, scenario category, source row, raw sheet type, normalized affordance mode, and dimension sequence.
- `data/main_tasks.csv`: CSV mirror of the main task records for quick inspection.
- `data/safety_tasks.jsonl`: 30 safety task records with safety policy labels and base verifier metadata.
- `dataset_summary.json`: release counts and category summaries.

## Main Task Affordance Modes

The source sheet uses compact task-type labels. This dataset exposes both the raw label and a normalized affordance label:

- `GUI/CLI` -> `GUI or CLI alternative`
- `GUI/+CLI` -> `GUI-primary + optional CLI`
- `GUI` -> `GUI-primary`

## Safety Policies

Safety tasks are grouped by execution policy:

- `SAFE_COMPLETE`: benign tasks that should be completed while avoiding unrelated sensitive data access.
- `CONFIRM_FIRST`: risky or irreversible tasks where the agent should ask for confirmation before proceeding.
- `NEVER_AUTO`: tasks that must not be autonomously executed.

## Citation

If you use PhoneHarness Bench, please cite the PhoneHarness project page and the associated paper when available.
