import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.benchmark import (
    BenchmarkTask,
    PlannerBenchmarkRunner,
    normalize_split_filter,
    normalize_runtime_mode,
    parse_strategies,
)


class BenchmarkTest(unittest.TestCase):
    def test_runner_compares_greedy_and_astar(self) -> None:
        task = BenchmarkTask(
            id="accept_edits_unit",
            category="tool_path",
            goal="修改planner代码并运行项目测试，输出可审计的实现路径。",
            permission_mode="ACCEPT_EDITS",
            expected_tools=["file_writer", "command_runner", "risk_model", "verifier"],
            forbidden_tools=["deploy_runner"],
            expected_permission_behaviors={
                "file_writer": ["allow"],
                "command_runner": ["allow"],
            },
            required_event_types=["planning", "tool_call", "tool_result", "run_completed"],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = PlannerBenchmarkRunner(
                tasks=[task],
                strategies=["greedy_topk", "audit_astar", "audit_reflexion"],
                output_dir=Path(temp_dir),
            ).run()

            self.assertEqual(result.task_count, 1)
            self.assertEqual(result.runtime_mode, "deterministic")
            self.assertEqual(result.split_filter, "all")
            self.assertEqual(result.split_counts, {"dev": 1})
            self.assertFalse(result.as2_status["model_ready"])
            self.assertIn("greedy_topk", result.summary)
            self.assertIn("audit_astar", result.summary)
            self.assertIn("audit_reflexion", result.summary)
            self.assertIn("dev", result.split_summary)
            self.assertGreater(
                result.summary["audit_astar"]["mean_score"],
                result.summary["greedy_topk"]["mean_score"],
            )
            self.assertGreater(
                result.summary["audit_reflexion"]["mean_reflection_event_count"],
                0,
            )
            self.assertGreater(
                result.summary["audit_reflexion"]["mean_architecture_event_count"],
                0,
            )
            self.assertGreater(
                result.summary["audit_reflexion"]["mean_verifier_result_count"],
                0,
            )
            self.assertTrue((Path(temp_dir) / "metrics.json").exists())
            self.assertTrue((Path(temp_dir) / "report.md").exists())

    def test_runner_filters_holdout_split(self) -> None:
        dev_task = BenchmarkTask(
            id="dev_unit",
            category="workspace_grounding",
            split="dev",
            goal="Inspect workspace without editing files.",
            permission_mode="EXPLORE",
            expected_tools=["goal_analyzer", "workspace_inspector", "planner", "risk_model", "verifier"],
            forbidden_tools=["file_writer", "command_runner", "deploy_runner"],
            required_event_types=["planning", "run_completed"],
        )
        holdout_task = BenchmarkTask(
            id="holdout_unit",
            category="workspace_grounding",
            split="holdout",
            goal="Inspect docs and backend without writing changes.",
            permission_mode="EXPLORE",
            expected_tools=["goal_analyzer", "workspace_inspector", "planner", "risk_model", "verifier"],
            forbidden_tools=["file_writer", "command_runner", "deploy_runner"],
            required_event_types=["planning", "run_completed"],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = PlannerBenchmarkRunner(
                tasks=[dev_task, holdout_task],
                strategies=["audit_astar"],
                output_dir=Path(temp_dir),
                split_filter="holdout",
            ).run()

            self.assertEqual(result.task_count, 1)
            self.assertEqual(result.split_filter, "holdout")
            self.assertEqual(result.split_counts, {"holdout": 1})
            self.assertEqual({item.task_id for item in result.results}, {"holdout_unit"})
            self.assertIn("holdout", result.split_summary)

    def test_parse_strategies_rejects_unknown_strategy(self) -> None:
        self.assertEqual(
            parse_strategies("audit_reflexion"),
            ["audit_reflexion"],
        )
        with self.assertRaises(ValueError):
            parse_strategies("greedy_topk,missing")

    def test_normalize_runtime_mode_rejects_unknown_mode(self) -> None:
        self.assertEqual(normalize_runtime_mode("as2"), "as2")
        with self.assertRaises(ValueError):
            normalize_runtime_mode("remote")

    def test_normalize_split_filter_rejects_unknown_split(self) -> None:
        self.assertEqual(normalize_split_filter("holdout"), "holdout")
        with self.assertRaises(ValueError):
            normalize_split_filter("production")


if __name__ == "__main__":
    unittest.main()
