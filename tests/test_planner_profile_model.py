import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.planner_profile_model import (
    PlannerProfileExample,
    clear_profile_model_cache,
    evaluate_profile_model,
    predict_goal_profile,
    save_profile_model,
    strip_profile_hints,
    train_profile_model,
)


class PlannerProfileModelTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_profile_model_cache()

    def test_strips_explicit_profile_hints(self) -> None:
        goal = (
            "Multi-source planner profile "
            "[source_family=tau2; planner_profile=policy_tool_agent; execution_tool=mcp_tool_runner]: "
            "Cancel a reservation under policy."
        )
        self.assertEqual(strip_profile_hints(goal), "Cancel a reservation under policy.")

    def test_trains_and_predicts_execution_profile(self) -> None:
        examples = [
            PlannerProfileExample(
                goal="Cancel an airline reservation after checking policy and confirmation.",
                planner_profile="policy_tool_agent",
                execution_tools=["mcp_tool_runner"],
                policy_mode="confirm",
                source_family="tau2",
            ),
            PlannerProfileExample(
                goal="Repair a failing build, edit files, and run validation commands.",
                planner_profile="skill_workflow",
                execution_tools=["file_writer", "command_runner"],
                policy_mode="act",
                source_family="skillsbench",
            ),
            PlannerProfileExample(
                goal="Fix broken code by editing source files and running tests.",
                planner_profile="skill_workflow",
                execution_tools=["file_writer", "command_runner"],
                policy_mode="act",
                source_family="skillsbench",
            ),
            PlannerProfileExample(
                goal="Open the Android app and complete the GUI workflow.",
                planner_profile="mobile_or_mcp_workflow",
                execution_tools=["mobile_gui_runner"],
                policy_mode="act",
                source_family="phoneharness",
            ),
        ]
        model = train_profile_model(examples)
        metrics = evaluate_profile_model(model, examples)
        self.assertEqual(metrics["execution_tools_accuracy"], 1.0)

        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "profile_policy_model.json"
            save_profile_model(model, model_path)
            prediction = predict_goal_profile(
                "Please fix the broken build by editing code and running tests.",
                model_path=model_path,
            )
            self.assertEqual(prediction.execution_tools, ["file_writer", "command_runner"])
            self.assertEqual(prediction.policy_mode, "act")

    def test_env_configured_model_can_be_loaded(self) -> None:
        examples = [
            PlannerProfileExample(
                goal="Use the support API tool to resolve a customer request.",
                planner_profile="api_planning",
                execution_tools=["mcp_tool_runner"],
                policy_mode="act",
                source_family="toolbench",
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "profile_policy_model.json"
            save_profile_model(train_profile_model(examples), model_path)
            with patch.dict("os.environ", {"OPENCLAW_PLANNER_PROFILE_MODEL": str(model_path)}, clear=False):
                clear_profile_model_cache()
                prediction = predict_goal_profile("Resolve a customer request with the support API tool.")
            self.assertEqual(prediction.execution_tools, ["mcp_tool_runner"])


if __name__ == "__main__":
    unittest.main()
