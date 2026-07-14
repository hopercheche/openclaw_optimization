import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.models import CandidateStep
from openclaw.permissions import PermissionEngine


class PermissionEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PermissionEngine()

    def test_explore_denies_mutating_step(self) -> None:
        step = CandidateStep(
            title="Write file",
            action="Write a file in the workspace.",
            tool_name="file_writer",
            rationale="Needs edit.",
            impact=4,
            evidence_value=3,
            reversibility=3,
            risk=3,
            mutates_workspace=True,
        )

        decision = self.engine.decide(step, "EXPLORE")

        self.assertEqual(decision.behavior, "deny")
        self.assertEqual(decision.rule, "mode_explore")

    def test_default_asks_for_mutating_step(self) -> None:
        step = CandidateStep(
            title="Run command",
            action="Run project validation command.",
            tool_name="command_runner",
            rationale="Needs validation.",
            impact=4,
            evidence_value=5,
            reversibility=3,
            risk=3,
            mutates_workspace=True,
        )

        decision = self.engine.decide(step, "DEFAULT")

        self.assertEqual(decision.behavior, "ask")
        self.assertTrue(decision.requires_human)

    def test_read_only_step_is_allowed(self) -> None:
        step = CandidateStep(
            title="Inspect",
            action="List project files.",
            tool_name="workspace_inspector",
            rationale="Read context.",
            impact=4,
            evidence_value=4,
            reversibility=5,
            risk=1,
        )

        decision = self.engine.decide(step, "DONT_ASK")

        self.assertEqual(decision.behavior, "allow")


if __name__ == "__main__":
    unittest.main()

