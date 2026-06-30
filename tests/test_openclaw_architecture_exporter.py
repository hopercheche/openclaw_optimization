import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "build_openclaw_architecture_trajectories.py"
)


def load_exporter_module():
    spec = importlib.util.spec_from_file_location("build_openclaw_architecture_trajectories", EXPORTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitectureExporterTest(unittest.TestCase):
    def test_exports_architecture_events_to_transitions_and_sft(self) -> None:
        exporter = load_exporter_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run_arch"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps({
                    "run_id": "run_arch",
                    "goal": "Optimize planner code and run validation.",
                    "permission_mode": "ACCEPT_EDITS",
                    "workspace_path": str(root),
                    "planner_strategy": "audit_reflexion",
                    "status": "completed",
                }),
                encoding="utf-8",
            )
            _write_events(run_dir / "events.jsonl", [
                {
                    "event_type": "planning",
                    "data": {"selected_tools": ["risk_model", "planner"]},
                },
                {
                    "event_type": "task_queue_created",
                    "data": {
                        "task_queue": [
                            {
                                "task_id": "run_arch-subtask-01",
                                "index": 1,
                                "title": "Review permission posture",
                                "objective": "Classify proposed actions.",
                                "tool_name": "risk_model",
                                "action": "Classify proposed actions into allow, ask, or deny.",
                                "model_tier": "small",
                                "risk_level": "low",
                                "context_policy": "permission_policy+risk_terms",
                                "memory_queries": ["tool:risk_model"],
                                "success_criteria": ["permission decision is recorded before execution"],
                                "executor_kind": "policy_gate",
                            }
                        ]
                    },
                },
                {
                    "event_type": "permission",
                    "data": {
                        "subtask_id": "run_arch-subtask-01",
                        "decision": {"behavior": "allow", "tool_name": "risk_model"},
                    },
                },
                {
                    "event_type": "tool_result",
                    "data": {
                        "subtask_id": "run_arch-subtask-01",
                        "tool_name": "risk_model",
                        "result": "Policy evidence captured.",
                    },
                },
                {
                    "event_type": "verifier_result",
                    "data": {
                        "subtask_id": "run_arch-subtask-01",
                        "tool_name": "risk_model",
                        "outcome": "completed",
                        "decision_behavior": "allow",
                        "evidence_complete": True,
                        "residual_risk": 0,
                        "next_action": "next_subtask",
                        "critique": "Looks good.",
                    },
                },
                {
                    "event_type": "planner_queue_closed",
                    "data": {"next_action": "complete"},
                },
            ])

            transitions_path = root / "out" / "transitions.jsonl"
            sft_path = root / "out" / "sft.jsonl"
            stats = exporter.export_architecture_trajectories(
                input_roots=[root],
                output_transitions=transitions_path,
                output_sft=sft_path,
                include_legacy=True,
            )

            self.assertEqual(stats["transitions"], 1)
            transition = json.loads(transitions_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(transition["domain_schema"], "openclaw_architecture_transition_v0")
            self.assertEqual(transition["action"]["planner_action"]["model_tier"], "small")
            self.assertEqual(transition["verifier"]["next_action"], "next_subtask")
            self.assertEqual(transition["reward"], 1.0)
            sft_row = json.loads(sft_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("<|im_start|>assistant", sft_row["text"])
            self.assertIn("openclaw.plan_subtask", sft_row["text"])

    def test_exports_legacy_events_when_architecture_events_are_absent(self) -> None:
        exporter = load_exporter_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run_legacy"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps({
                    "run_id": "run_legacy",
                    "goal": "Inspect workspace safely.",
                    "permission_mode": "EXPLORE",
                    "workspace_path": str(root),
                    "planner_strategy": "audit_astar",
                    "status": "completed",
                }),
                encoding="utf-8",
            )
            _write_events(run_dir / "events.jsonl", [
                {
                    "event_type": "planning",
                    "data": {"selected_tools": ["workspace_inspector"]},
                },
                {
                    "event_type": "reasoning",
                    "data": {
                        "step": {
                            "title": "Inspect workspace safely",
                            "action": "List project files.",
                            "tool_name": "workspace_inspector",
                            "rationale": "Ground the planner in real files.",
                            "risk": 1,
                            "mutates_workspace": False,
                        }
                    },
                },
                {
                    "event_type": "permission",
                    "data": {
                        "step_title": "Inspect workspace safely",
                        "decision": {"behavior": "allow", "tool_name": "workspace_inspector"},
                    },
                },
                {
                    "event_type": "tool_result",
                    "data": {"tool_name": "workspace_inspector", "result": "README.md"},
                },
            ])

            transitions_path = root / "out" / "legacy_transitions.jsonl"
            sft_path = root / "out" / "legacy_sft.jsonl"
            stats = exporter.export_architecture_trajectories(
                input_roots=[root],
                output_transitions=transitions_path,
                output_sft=sft_path,
                include_legacy=True,
            )

            self.assertEqual(stats["transitions"], 1)
            transition = json.loads(transitions_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertTrue(transition["source"]["legacy"])
            self.assertEqual(transition["action"]["planner_action"]["context_policy"], "legacy_event_replay")
            self.assertEqual(transition["verifier"]["outcome"], "completed")


def _write_events(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index, event in enumerate(events, start=1):
            payload = {
                "run_id": path.parent.name,
                "event_id": index,
                "event_type": event["event_type"],
                "message": event.get("message", event["event_type"]),
                "data": event.get("data", {}),
                "timestamp": "2026-06-30T00:00:00Z",
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
