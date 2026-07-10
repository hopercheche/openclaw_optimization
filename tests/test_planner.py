import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.as2_adapter import AS2Status
from openclaw.models import CandidateStep, RunState, new_run_id
from openclaw.permissions import PermissionEngine
from openclaw.planner import LocalAuditPlanner
from openclaw.storage import RunStorage


class PlannerTest(unittest.TestCase):
    def test_planner_writes_events_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal="Create an auditable plan",
                permission_mode="DEFAULT",
                workspace_path=temp_dir,
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
            )

            planner.run(state)

            saved = storage.load_state(state.run_id)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.status, "completed")
            events = storage.load_events(state.run_id)
            self.assertGreaterEqual(len(events), 5)
            self.assertEqual([event.event_id for event in events], list(range(1, len(events) + 1)))
            self.assertEqual(saved.event_count, len(events))
            self.assertIn("run_completed", {event.event_type for event in events})
            self.assertTrue(all("as2_event_type" in event.data for event in events))
            audit = storage.read_audit(state.run_id)
            self.assertIsNotNone(audit)
            self.assertIn("# Audit Report:", audit)

    def test_routed_model_policy_skips_confident_local_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"OPENCLAW_MODEL_PLANNER_POLICY": "routed"},
            clear=False,
        ):
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal="Inspect the repository and explain the audit boundary",
                permission_mode="DEFAULT",
                workspace_path=temp_dir,
            )
            storage.create_run(state)
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=True,
                    package_version="test",
                    runtime="test",
                    note="test",
                    model_ready=True,
                    model_provider="dashscope",
                    model_base_url="https://example.test/v1",
                    default_model="qwen3.7-max",
                ),
            )

            planner.run(state)

            events = storage.load_events(state.run_id)
            event_types = [event.event_type for event in events]
            self.assertIn("as2_model_skipped", event_types)
            self.assertNotIn("as2_model_started", event_types)
            skip_events = [event for event in events if event.event_type == "as2_model_skipped"]
            self.assertEqual(skip_events[0].data["model_policy"], "routed")
            self.assertEqual(skip_events[0].data["route_reason"], "deterministic_planner_confident")

    def test_model_candidates_only_expand_missing_tool_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            state = RunState(
                run_id=new_run_id(),
                goal="PhoneHarness planner_profile=mobile execution_tool=mobile_gui_runner complete a safe flow",
                permission_mode="DEFAULT",
                workspace_path=temp_dir,
            )
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=True,
                    package_version="test",
                    runtime="test",
                    note="test",
                    model_ready=True,
                ),
            )

            merged = planner._augment_model_candidates(
                state,
                [
                    CandidateStep(
                        title="Model mobile step",
                        action="Use mobile GUI directly.",
                        tool_name="mobile_gui_runner",
                        rationale="model candidate",
                        impact=5,
                        evidence_value=5,
                        reversibility=5,
                        risk=1,
                    ),
                    CandidateStep(
                        title="Model novel audit reader step",
                        action="Read a supplemental audit artifact.",
                        tool_name="audit_reader",
                        rationale="model expansion candidate",
                        impact=5,
                        evidence_value=5,
                        reversibility=5,
                        risk=1,
                    ),
                ],
            )

            titles_by_tool = {candidate.tool_name: candidate.title for candidate in merged}
            self.assertNotEqual(titles_by_tool["mobile_gui_runner"], "Model mobile step")
            self.assertEqual(titles_by_tool["audit_reader"], "Model novel audit reader step")


if __name__ == "__main__":
    unittest.main()
