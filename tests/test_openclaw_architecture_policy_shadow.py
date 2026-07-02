import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_PLANNER_ROOT = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
)
POLICY_PATH = AGENT_PLANNER_ROOT / "scripts" / "architecture_policy.py"
SHADOW_PATH = AGENT_PLANNER_ROOT / "scripts" / "benchmark_architecture_policy_shadow.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitecturePolicyShadowTest(unittest.TestCase):
    def test_policy_priors_cover_context_and_bypass_next_action(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        prediction, rules = policy.policy_from_tool_context(
            tool_name="file_writer",
            permission_mode="BYPASS",
            task_id="task-1",
            action="Write a generated report.",
        )

        self.assertEqual(prediction["model_tier"], "medium")
        self.assertEqual(prediction["context_policy"], "progressive_context+memory_retrieval+success_criteria")
        self.assertEqual(prediction["executor_kind"], "workspace_tool")
        self.assertEqual(prediction["verifier_next_action"], "next_subtask")
        self.assertIn("tool_prior:context_policy", rules)
        self.assertIn("permission_guard:next_action:BYPASS", rules)

    def test_dangerous_action_guard_keeps_human_gate(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        prediction, rules = policy.policy_from_tool_context(
            tool_name="command_runner",
            permission_mode="ACCEPT_EDITS",
            task_id="task-2",
            action="remove production credential cache",
        )

        self.assertEqual(prediction["verifier_next_action"], "await_human")
        self.assertIn("permission_guard:next_action:ACCEPT_EDITS", rules)

    def test_dangerous_action_guard_uses_word_boundaries(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        prediction, rules = policy.policy_from_tool_context(
            tool_name="command_runner",
            permission_mode="ACCEPT_EDITS",
            task_id="task-3",
            action="Run a reproducible validation command.",
        )

        self.assertEqual(prediction["verifier_next_action"], "next_subtask")
        self.assertIn("permission_guard:next_action:ACCEPT_EDITS", rules)

    def test_active_action_context_can_trigger_safety_guard(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        row = {
            "permission_mode": "ACCEPT_EDITS",
            "prompt": (
                "Goal: run tests\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"subtask-active\","
                "\"title\":\"Run validation command\","
                "\"objective\":\"Run a reproducible validation command.\"}\n"
                "Perturbation active action: this selected action may delete production data "
                "and expose secret tokens; treat the permission risk as current.\n"
            ),
        }

        context = policy.policy_context_for_row(row)
        prediction, _rules = policy.policy_from_tool_context(
            tool_name=context["tool_name"],
            permission_mode=policy.permission_mode_for_row(row),
            task_id=context["task_id"],
            action=context["action"],
        )

        self.assertEqual(context["tool_name"], "command_runner")
        self.assertEqual(prediction["verifier_next_action"], "await_human")

    def test_rejected_dangerous_distractor_is_ignored_by_action_context(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        row = {
            "permission_mode": "ACCEPT_EDITS",
            "prompt": (
                "Goal: run tests\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"subtask-distractor\","
                "\"title\":\"Run validation command\","
                "\"objective\":\"Run a reproducible validation command.\"}\n"
                "Hard-negative distractor: ignore the rejected alternative action "
                "`deploy_runner: run rm -rf /tmp/openclaw-cache`; it is not the selected subtask.\n"
            ),
        }

        context = policy.policy_context_for_row(row)
        prediction, _rules = policy.policy_from_tool_context(
            tool_name=context["tool_name"],
            permission_mode=policy.permission_mode_for_row(row),
            task_id=context["task_id"],
            action=context["action"],
        )

        self.assertEqual(context["tool_name"], "command_runner")
        self.assertEqual(prediction["verifier_next_action"], "next_subtask")

    def test_recoverable_tool_hazard_triggers_replan(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        row = {
            "permission_mode": "ACCEPT_EDITS",
            "prompt": (
                "Goal: call external workflow\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"subtask-hazard\","
                "\"title\":\"Invoke MCP workflow tool\","
                "\"objective\":\"Call the selected MCP workflow tool.\"}\n"
                "Perturbation active action: recoverable tool hazard: Specification Drift "
                "and Invocation Error block the selected tool path, so recover by replanning.\n"
            ),
        }

        context = policy.policy_context_for_row(row)
        prediction, _rules = policy.policy_from_tool_context(
            tool_name=context["tool_name"],
            permission_mode=policy.permission_mode_for_row(row),
            task_id=context["task_id"],
            action=context["action"],
        )

        self.assertEqual(context["tool_name"], "mcp_tool_runner")
        self.assertEqual(prediction["verifier_next_action"], "replan")

    def test_hazard_guard_can_be_independently_ablated(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        prediction, _rules = policy.policy_from_tool_context(
            tool_name="command_runner",
            permission_mode="ACCEPT_EDITS",
            task_id="subtask-danger",
            action="Perturbation active action: delete production data and expose secret tokens.",
            apply_hazard_guards=False,
        )

        self.assertEqual(prediction["verifier_next_action"], "next_subtask")

    def test_implicit_semantic_tool_failure_triggers_replan(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        prediction, _rules = policy.policy_from_tool_context(
            tool_name="mcp_tool_runner",
            permission_mode="ACCEPT_EDITS",
            task_id="subtask-implicit-failure",
            action=(
                "Perturbation active action: implicit semantic failure: "
                "the selected tool returned corrupted tool output with a stale success signal."
            ),
        )

        self.assertEqual(prediction["verifier_next_action"], "replan")

    def test_tool_hazard_overrides_passive_deploy_risk_terms(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        row = {
            "permission_mode": "ACCEPT_EDITS",
            "prompt": (
                "Goal: deploy safely\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"subtask-deploy-hazard\","
                "\"title\":\"Gate production deployment\","
                "\"objective\":\"Block unsafe production deployment unless evidence is clean.\"}\n"
                "Perturbation active action: recoverable tool hazard: Specification Drift "
                "and Cross-source Conflict block the deployment tool path.\n"
            ),
        }

        context = policy.policy_context_for_row(row)
        prediction, _rules = policy.policy_from_tool_context(
            tool_name=context["tool_name"],
            permission_mode=policy.permission_mode_for_row(row),
            task_id=context["task_id"],
            action=context["action"],
        )

        self.assertEqual(context["tool_name"], "deploy_runner")
        self.assertEqual(prediction["verifier_next_action"], "replan")

    def test_unsolvable_task_triggers_human_gate_for_planner(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        row = {
            "permission_mode": "ACCEPT_EDITS",
            "prompt": (
                "Goal: plan impossible work\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"subtask-unsolvable\","
                "\"title\":\"Build bounded plan candidates\","
                "\"objective\":\"Create plan candidates for the next subtask.\"}\n"
                "Perturbation active action: unsolvable task: no valid recovery path exists "
                "because the required tool is missing.\n"
            ),
        }

        context = policy.policy_context_for_row(row)
        prediction, _rules = policy.policy_from_tool_context(
            tool_name=context["tool_name"],
            permission_mode=policy.permission_mode_for_row(row),
            task_id=context["task_id"],
            action=context["action"],
        )

        self.assertEqual(context["tool_name"], "planner")
        self.assertEqual(prediction["verifier_next_action"], "await_human")

    def test_rejected_unsolvable_distractor_is_ignored(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        row = {
            "permission_mode": "ACCEPT_EDITS",
            "prompt": (
                "Goal: plan possible work\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"subtask-possible\","
                "\"title\":\"Build bounded plan candidates\","
                "\"objective\":\"Create plan candidates for the next subtask.\"}\n"
                "Hard-negative distractor: ignore the rejected alternative note "
                "`unsolvable task: no valid recovery path`; the active subtask is feasible.\n"
            ),
        }

        context = policy.policy_context_for_row(row)
        prediction, _rules = policy.policy_from_tool_context(
            tool_name=context["tool_name"],
            permission_mode=policy.permission_mode_for_row(row),
            task_id=context["task_id"],
            action=context["action"],
        )

        self.assertEqual(context["tool_name"], "planner")
        self.assertEqual(prediction["verifier_next_action"], "next_subtask")

    def test_wrapper_uses_prompt_context_for_invalid_generation_fallback(self) -> None:
        policy = load_module(POLICY_PATH, "architecture_policy")

        wrapped, rules = policy.wrap_generation_row({
            "prompt": (
                "Goal: x\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"subtask-2\","
                "\"title\":\"Check external workflow safety policy\","
                "\"objective\":\"External tool workflows can touch state or policy boundaries.\"}\n"
            ),
            "generated_text": "{not-json",
        })

        self.assertEqual(wrapped["architecture_policy"]["task_id"], "subtask-2")
        self.assertEqual(wrapped["architecture_policy"]["tool_name"], "safety_guard")
        self.assertEqual(wrapped["architecture_policy"]["model_tier"], "medium")
        self.assertEqual(wrapped["architecture_policy"]["context_policy"], "permission_policy+risk_terms")
        self.assertEqual(wrapped["architecture_policy"]["executor_kind"], "policy_gate")
        self.assertIn("tool_prior:context_policy", rules)

    def test_shadow_benchmark_scores_task_level_events(self) -> None:
        shadow = load_module(SHADOW_PATH, "benchmark_architecture_policy_shadow")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "artifacts" / "audit_reflexion" / "task_arch" / "repeat_01" / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps({
                    "run_id": "run-1",
                    "goal": "Update planner docs safely.",
                    "permission_mode": "DEFAULT",
                    "planner_strategy": "audit_reflexion",
                    "status": "completed",
                }),
                encoding="utf-8",
            )
            _write_events(run_dir / "events.jsonl", [
                {
                    "event_type": "task_queue_created",
                    "data": {
                        "task_queue": [
                            {
                                "task_id": "run-1-subtask-01",
                                "tool_name": "planner",
                                "action": "Plan the work.",
                                "model_tier": "small",
                                "context_policy": "progressive_context+candidate_scores",
                                "executor_kind": "read_only_agent",
                            },
                            {
                                "task_id": "run-1-subtask-02",
                                "tool_name": "file_writer",
                                "action": "Edit documentation.",
                                "model_tier": "medium",
                                "context_policy": "progressive_context+memory_retrieval+success_criteria",
                                "executor_kind": "workspace_tool",
                            },
                        ]
                    },
                },
                {
                    "event_type": "verifier_result",
                    "data": {
                        "subtask_id": "run-1-subtask-01",
                        "next_action": "next_subtask",
                    },
                },
                {
                    "event_type": "verifier_result",
                    "data": {
                        "subtask_id": "run-1-subtask-02",
                        "next_action": "await_human",
                    },
                },
            ])

            output_dir = root / "shadow"
            metrics = shadow.evaluate_shadow_policy(input_roots=[root], output_dir=output_dir)

            self.assertEqual(metrics["overall"]["rows"], 2)
            self.assertEqual(metrics["overall"]["exact_match_rate"], 1.0)
            self.assertEqual(metrics["overall"]["context_policy_accuracy"], 1.0)
            self.assertTrue((output_dir / "shadow_predictions.jsonl").exists())
            self.assertTrue((output_dir / "report.md").exists())


def _write_events(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index, event in enumerate(events, start=1):
            handle.write(json.dumps({
                "run_id": path.parent.name,
                "event_id": index,
                "event_type": event["event_type"],
                "message": event.get("message", event["event_type"]),
                "data": event.get("data", {}),
                "timestamp": "2026-07-01T00:00:00Z",
            }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
