import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.as2_adapter import AS2Status
from openclaw.models import RunState, new_run_id
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
            self.assertIn("run_completed", {event.event_type for event in events})
            self.assertTrue(all("as2_event_type" in event.data for event in events))
            audit = storage.read_audit(state.run_id)
            self.assertIsNotNone(audit)
            self.assertIn("# Audit Report:", audit)


if __name__ == "__main__":
    unittest.main()
