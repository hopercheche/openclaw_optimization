import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "summarize_architecture_policy_runs.py"
)


def load_summary_module():
    spec = importlib.util.spec_from_file_location("summarize_architecture_policy_runs", SUMMARY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitectureSummaryTest(unittest.TestCase):
    def test_summarizes_metrics_summary_and_generation_fallback(self) -> None:
        summary_module = load_summary_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metrics_run = root / "metrics_run"
            summary_run = root / "summary_run"
            generations_run = root / "generations_run"
            ignored_run = root / "ignored_run"
            metrics_run.mkdir()
            summary_run.mkdir()
            generations_run.mkdir()
            ignored_run.mkdir()

            (metrics_run / "metrics.json").write_text(
                json.dumps({
                    "overall": {
                        "rows": 4,
                        "schema_valid_count": 3,
                        "normalized_count": 1,
                        "model_tier_correct": 2,
                        "model_tier_total": 4,
                        "next_action_accuracy": 0.75,
                        "context_policy_correct": 3,
                        "context_policy_total": 4,
                        "executor_kind_accuracy": 1.0,
                    }
                }),
                encoding="utf-8",
            )
            (summary_run / "summary.json").write_text(
                json.dumps({
                    "rows": 2,
                    "schema_valid_rate": 1.0,
                    "normalized_rate": 0.5,
                    "model_tier_accuracy": 1.0,
                    "next_action_accuracy": 0.5,
                    "context_policy_accuracy": 1.0,
                    "executor_kind_correct": 1,
                    "executor_kind_total": 2,
                }),
                encoding="utf-8",
            )
            _write_jsonl(
                generations_run / "generations.jsonl",
                [
                    {
                        "schema": {"schema_valid": True},
                        "normalized": True,
                        "matches": {
                            "model_tier": True,
                            "next_action": False,
                            "context_policy": True,
                            "executor_kind": True,
                        },
                    },
                    {
                        "schema": {"schema_valid": False},
                        "expected": {
                            "model_tier": "small",
                            "next_action": "replan",
                            "context_policy": "legacy_event_replay",
                            "executor_kind": "policy_gate",
                        },
                        "predictions": {
                            "model_tier": "medium",
                            "next_action": "replan",
                            "context_policy": "legacy_event_replay",
                            "executor_kind": "command",
                        },
                    },
                ],
            )
            (ignored_run / "metrics.json").write_text(
                json.dumps({"result": {"schema_valid_rate": 1.0, "generation_examples": 8}}),
                encoding="utf-8",
            )

            summary = summary_module.summarize_paths([root], recursive=True)
            by_name = {run["run_name"]: run for run in summary["runs"]}

            self.assertEqual(set(by_name), {"generations_run", "metrics_run", "summary_run"})
            self.assertEqual(by_name["metrics_run"]["rows"], 4)
            self.assertEqual(by_name["metrics_run"]["schema_valid_rate"], 0.75)
            self.assertEqual(by_name["metrics_run"]["normalized_count"], 1)
            self.assertEqual(by_name["metrics_run"]["model_tier_accuracy"], 0.5)
            self.assertEqual(by_name["metrics_run"]["next_action_accuracy"], 0.75)
            self.assertEqual(by_name["metrics_run"]["context_policy_accuracy"], 0.75)
            self.assertEqual(by_name["metrics_run"]["executor_kind_accuracy"], 1.0)

            self.assertEqual(by_name["summary_run"]["rows"], 2)
            self.assertEqual(by_name["summary_run"]["normalized_count"], 1)
            self.assertEqual(by_name["summary_run"]["executor_kind_accuracy"], 0.5)

            self.assertEqual(by_name["generations_run"]["rows"], 2)
            self.assertEqual(by_name["generations_run"]["schema_valid_rate"], 0.5)
            self.assertEqual(by_name["generations_run"]["normalized_count"], 1)
            self.assertEqual(by_name["generations_run"]["model_tier_accuracy"], 0.5)
            self.assertEqual(by_name["generations_run"]["next_action_accuracy"], 0.5)
            self.assertEqual(by_name["generations_run"]["context_policy_accuracy"], 1.0)
            self.assertEqual(by_name["generations_run"]["executor_kind_accuracy"], 0.5)
            self.assertTrue(summary["skipped"])

    def test_cli_writes_markdown_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "architecture_policy_eval"
            run_dir.mkdir()
            output_path = root / "summary.md"
            (run_dir / "metrics.json").write_text(
                json.dumps({
                    "overall": {
                        "rows": 3,
                        "schema_valid_rate": 0.6667,
                        "normalized_count": 1,
                        "model_tier_accuracy": 1.0,
                        "next_action_accuracy": 0.3333,
                        "context_policy_accuracy": 0.6667,
                        "executor_kind_accuracy": 0.0,
                    }
                }),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SUMMARY_PATH),
                    str(root),
                    "--format",
                    "markdown",
                    "--output",
                    str(output_path),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            rendered = output_path.read_text(encoding="utf-8")
            self.assertIn("# OpenClaw Architecture Policy Run Summary", rendered)
            self.assertIn("| architecture_policy_eval | 3 | 66.67% | 1 | 100.00% | 33.33% | 66.67% | 0.00% |", rendered)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
