import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.as2_adapter import AS2Status
from openclaw.models import RunState, new_run_id
from openclaw.permissions import PermissionEngine
from openclaw.planner import LocalAuditPlanner
from openclaw.search_planner import normalize_planner_strategy
from openclaw.storage import RunStorage


class SearchPlannerTest(unittest.TestCase):
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

    def test_unknown_strategy_normalizes_to_baseline(self) -> None:
        self.assertEqual(normalize_planner_strategy("unknown"), "greedy_topk")
        self.assertEqual(normalize_planner_strategy("audit_reflexion"), "audit_reflexion")


if __name__ == "__main__":
    unittest.main()
