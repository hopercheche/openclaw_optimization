import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.as2_adapter import AS2Status
from openclaw.models import RunState, new_run_id
from openclaw.permissions import PermissionEngine
from openclaw.planner import LocalAuditPlanner
from openclaw.planner_profile_model import (
    PlannerProfileExample,
    clear_profile_model_cache,
    save_profile_model,
    train_profile_model,
)
from openclaw.search_planner import normalize_planner_strategy
from openclaw.storage import RunStorage


class SearchPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = patch.dict(
            "os.environ",
            {"OPENCLAW_DISABLE_PLANNER_PROFILE_MODEL": "1"},
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_audit_astar_emits_search_trace_and_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal="Optimize the planner and edit files only after checking audit risk",
                permission_mode="ACCEPT_EDITS",
                workspace_path=temp_dir,
                planner_strategy="audit_astar",
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
                planner_strategy="audit_astar",
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            event_types = {event.event_type for event in events}
            self.assertIn("search_started", event_types)
            self.assertIn("search_expand", event_types)
            self.assertIn("search_score", event_types)
            self.assertIn("search_selected", event_types)

            planning_event = next(event for event in events if event.event_type == "planning")
            self.assertEqual(planning_event.data["planner_strategy"], "audit_astar")
            self.assertIn("audit_astar_priority", planning_event.data["selection_rule"])

            audit = storage.read_audit(state.run_id)
            self.assertIsNotNone(audit)
            self.assertIn("- Planner strategy: audit_astar", audit)

    def test_audit_reflexion_repairs_mutating_path_and_emits_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal="Optimize planner code, edit files, and run validation tests after audit review",
                permission_mode="ACCEPT_EDITS",
                workspace_path=temp_dir,
                planner_strategy="audit_reflexion",
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
                planner_strategy="audit_reflexion",
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            event_types = {event.event_type for event in events}
            self.assertIn("search_selected", event_types)
            self.assertIn("reflection_started", event_types)
            self.assertIn("reflection_refined", event_types)

            planning_event = next(event for event in events if event.event_type == "planning")
            self.assertEqual(planning_event.data["planner_strategy"], "audit_reflexion")
            self.assertIn("audit_reflexion", planning_event.data["selection_rule"])
            selected_tools = set(planning_event.data["selected_tools"])
            self.assertEqual(
                selected_tools,
                {"risk_model", "planner", "file_writer", "command_runner", "verifier"},
            )

    def test_planner_emits_architecture_aligned_subtask_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal="Optimize planner code, edit files, and run validation tests after audit review",
                permission_mode="ACCEPT_EDITS",
                workspace_path=temp_dir,
                planner_strategy="audit_reflexion",
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
                planner_strategy="audit_reflexion",
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            event_types = [event.event_type for event in events]
            for expected in [
                "architecture_snapshot",
                "task_queue_created",
                "subtask_started",
                "strategist_model_selection",
                "architect_context",
                "executor_started",
                "verifier_result",
                "planner_queue_closed",
            ]:
                self.assertIn(expected, event_types)

            queue_event = next(event for event in events if event.event_type == "task_queue_created")
            task_queue = queue_event.data["task_queue"]
            self.assertGreaterEqual(len(task_queue), 1)
            for key in [
                "task_id",
                "model_tier",
                "risk_level",
                "context_policy",
                "memory_queries",
                "success_criteria",
                "executor_kind",
            ]:
                self.assertIn(key, task_queue[0])

            strategist_events = [event for event in events if event.event_type == "strategist_model_selection"]
            architect_events = [event for event in events if event.event_type == "architect_context"]
            self.assertEqual(len(strategist_events), len(task_queue))
            self.assertEqual(len(architect_events), len(task_queue))
            self.assertIn("medium", {event.data["model_tier"] for event in strategist_events})
            self.assertTrue(any(event.data["success_criteria"] for event in architect_events))

            queue_closed = next(event for event in events if event.event_type == "planner_queue_closed")
            self.assertEqual(queue_closed.data["blocked_count"], 0)
            self.assertEqual(queue_closed.data["next_action"], "complete")

    def test_audit_reflexion_keeps_explicit_read_only_path_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal="Inspect workspace without editing or writing files, then summarize audit risks",
                permission_mode="EXPLORE",
                workspace_path=temp_dir,
                planner_strategy="audit_reflexion",
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
                planner_strategy="audit_reflexion",
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            planning_event = next(event for event in events if event.event_type == "planning")
            selected_tools = planning_event.data["selected_tools"]
            self.assertEqual(
                set(selected_tools),
                {"goal_analyzer", "workspace_inspector", "planner", "risk_model", "verifier"},
            )
            self.assertNotIn("file_writer", selected_tools)
            self.assertNotIn("command_runner", selected_tools)

    def test_reflexion_uses_profile_aligned_shortcut_for_policy_tool_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal=(
                    "Multi-source planner profile "
                    "[source_family=tau2; planner_profile=policy_tool_agent; "
                    "safety_policy=SAFE_COMPLETE; execution_tool=mcp_tool_runner]: "
                    "Resolve a customer issue using domain tools and policy checks."
                ),
                permission_mode="ACCEPT_EDITS",
                workspace_path=temp_dir,
                planner_strategy="audit_reflexion",
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
                planner_strategy="audit_reflexion",
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            planning_event = next(event for event in events if event.event_type == "planning")
            selected_tools = planning_event.data["selected_tools"]
            self.assertEqual(
                selected_tools,
                ["risk_model", "safety_guard", "planner", "mcp_tool_runner", "verifier"],
            )
            search_events = [event for event in events if event.event_type.startswith("search_")]
            self.assertLess(len(search_events), 20)
            selected_event = next(event for event in events if event.event_type == "search_selected")
            self.assertEqual(selected_event.data["expanded_nodes"], 1)

    def test_audit_astar_treats_profile_policy_mode_as_safety_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal=(
                    "Multi-source planner profile "
                    "[source_family=tau2; planner_profile=policy_tool_agent; "
                    "execution_tool=mcp_tool_runner; policy_mode=confirm]: "
                    "Confirm policy constraints before using the domain tool."
                ),
                permission_mode="DEFAULT",
                workspace_path=temp_dir,
                planner_strategy="audit_astar",
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
                planner_strategy="audit_astar",
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            planning_event = next(event for event in events if event.event_type == "planning")
            self.assertEqual(
                planning_event.data["selected_tools"],
                ["risk_model", "safety_guard", "planner", "mcp_tool_runner", "verifier"],
            )
            selected_event = next(event for event in events if event.event_type == "search_selected")
            self.assertEqual(selected_event.data["expanded_nodes"], 1)

    def test_reflexion_uses_profile_aligned_shortcut_for_skill_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal=(
                    "Multi-source planner profile "
                    "[source_family=skillsbench; planner_profile=skill_workflow; "
                    "execution_tools=file_writer,command_runner; policy_mode=act]: "
                    "Repair a build and run the validation command."
                ),
                permission_mode="ACCEPT_EDITS",
                workspace_path=temp_dir,
                planner_strategy="audit_reflexion",
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
                planner_strategy="audit_reflexion",
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            planning_event = next(event for event in events if event.event_type == "planning")
            self.assertEqual(
                planning_event.data["selected_tools"],
                ["risk_model", "planner", "file_writer", "command_runner", "verifier"],
            )
            selected_event = next(event for event in events if event.event_type == "search_selected")
            self.assertEqual(selected_event.data["expanded_nodes"], 1)

    def test_unknown_strategy_normalizes_to_baseline(self) -> None:
        self.assertEqual(normalize_planner_strategy("unknown"), "greedy_topk")
        self.assertEqual(normalize_planner_strategy("audit_reflexion"), "audit_reflexion")


class LearnedProfileSearchPlannerTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_profile_model_cache()

    def test_high_confidence_skill_profile_passes_local_project_guard(self) -> None:
        goal = (
            "Implement planner code files for a drone simulation and run command "
            "validation for every natural language command."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "profile_policy_model.json"
            save_profile_model(
                train_profile_model([
                    PlannerProfileExample(
                        goal=goal,
                        planner_profile="skill_workflow",
                        execution_tools=["file_writer", "command_runner"],
                        policy_mode="act",
                        source_family="skillsbench",
                    ),
                    PlannerProfileExample(
                        goal="Use a support API tool to resolve the customer request.",
                        planner_profile="api_planning",
                        execution_tools=["mcp_tool_runner"],
                        policy_mode="act",
                        source_family="toolbench",
                    ),
                ]),
                model_path,
            )
            with patch.dict("os.environ", {"OPENCLAW_PLANNER_PROFILE_MODEL": str(model_path)}, clear=True):
                clear_profile_model_cache()
                storage = RunStorage(Path(temp_dir) / "storage")
                state = RunState(
                    run_id=new_run_id(),
                    goal=goal,
                    permission_mode="ACCEPT_EDITS",
                    workspace_path=temp_dir,
                    planner_strategy="audit_astar",
                )
                storage.create_run(state)
                planner = LocalAuditPlanner(
                    storage=storage,
                    permission_engine=PermissionEngine(),
                    as2_status=AS2Status(
                        available=False,
                        package_version=None,
                        runtime="test",
                        note="test",
                    ),
                    planner_strategy="audit_astar",
                )

                planner.run(state)

            events = storage.load_events(state.run_id)
            planning_event = next(event for event in events if event.event_type == "planning")
            self.assertEqual(
                planning_event.data["selected_tools"],
                ["risk_model", "planner", "file_writer", "command_runner", "verifier"],
            )


if __name__ == "__main__":
    unittest.main()
