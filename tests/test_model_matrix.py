import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.benchmark import BenchmarkTask
from openclaw.model_matrix import ModelMatrixEntry, PlannerModelMatrixRunner


class ModelMatrixTest(unittest.TestCase):
    def test_runner_writes_matrix_outputs_and_missing_env_metadata(self) -> None:
        task = BenchmarkTask(
            id="matrix_unit",
            category="workspace_grounding",
            goal="Inspect workspace without editing files.",
            permission_mode="EXPLORE",
            expected_tools=["goal_analyzer", "workspace_inspector", "planner", "risk_model", "verifier"],
            forbidden_tools=["file_writer", "command_runner", "deploy_runner"],
            required_event_types=["planning", "run_completed"],
        )
        entries = [
            ModelMatrixEntry(name="deterministic_unit", runtime="deterministic"),
            ModelMatrixEntry(
                name="as2_missing_key_unit",
                runtime="as2",
                required_env=["OPENCLAW_MISSING_TEST_KEY"],
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = PlannerModelMatrixRunner(
                tasks=[task],
                entries=entries,
                output_dir=Path(temp_dir),
                strategies=["audit_astar"],
                repeat_count=1,
            ).run()

            self.assertEqual(len(result.entries), 2)
            self.assertTrue((Path(temp_dir) / "matrix_metrics.json").exists())
            self.assertTrue((Path(temp_dir) / "matrix_report.md").exists())

            missing_key_entry = next(entry for entry in result.entries if entry.name == "as2_missing_key_unit")
            self.assertFalse(missing_key_entry.required_env_present)
            self.assertEqual(missing_key_entry.missing_required_env, ["OPENCLAW_MISSING_TEST_KEY"])
            self.assertFalse(missing_key_entry.as2_status["model_ready"])
            self.assertGreater(
                missing_key_entry.model_metrics["overall"]["model_skipped_count"],
                0,
            )

    def test_entry_rejects_secret_env_overrides(self) -> None:
        with self.assertRaises(ValueError):
            ModelMatrixEntry.from_dict({
                "name": "bad_secret",
                "runtime": "as2",
                "env": {"OPENAI_API_KEY": "not-allowed"},
            })


if __name__ == "__main__":
    unittest.main()
