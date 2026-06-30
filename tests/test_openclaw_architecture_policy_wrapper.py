import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "apply_architecture_policy_wrapper.py"
)


def load_wrapper_module():
    spec = importlib.util.spec_from_file_location("apply_architecture_policy_wrapper", WRAPPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitecturePolicyWrapperTest(unittest.TestCase):
    def test_tool_prior_fixes_deterministic_policy_gate_fields(self) -> None:
        wrapper = load_wrapper_module()
        row = {
            "generated_text": json.dumps({
                "task_id": "task-1",
                "tool_name": "risk_model",
                "model_tier": "medium",
                "context_policy": "permission_policy+safety_terms",
                "executor_kind": "risk_model",
                "verifier_next_action": "await_human",
            })
        }

        wrapped, rules = wrapper.wrap_generation_row(row)

        self.assertEqual(wrapped["architecture_policy"]["model_tier"], "small")
        self.assertEqual(wrapped["architecture_policy"]["context_policy"], "permission_policy+risk_terms")
        self.assertEqual(wrapped["architecture_policy"]["executor_kind"], "policy_gate")
        self.assertEqual(wrapped["architecture_policy"]["verifier_next_action"], "next_subtask")
        self.assertIn("tool_prior:model_tier", rules)
        self.assertIn("tool_prior:next_action", rules)

    def test_wrapper_preserves_variable_next_action_for_execution_tools(self) -> None:
        wrapper = load_wrapper_module()
        row = {
            "task_preview": "Goal: x Permission mode: BYPASS Planner strategy: audit_astar",
            "generated_text": json.dumps({
                "task_id": "task-2",
                "tool_name": "file_writer",
                "model_tier": "small",
                "context_policy": "progressive_context+memory_retrieval+success_criteria",
                "executor_kind": "command_runner",
                "verifier_next_action": "replan",
            })
        }

        wrapped, rules = wrapper.wrap_generation_row(row)

        self.assertEqual(wrapped["architecture_policy"]["model_tier"], "medium")
        self.assertEqual(wrapped["architecture_policy"]["executor_kind"], "workspace_tool")
        self.assertEqual(wrapped["architecture_policy"]["verifier_next_action"], "replan")
        self.assertNotIn("tool_prior:next_action", rules)
        self.assertFalse(any(rule.startswith("permission_guard:next_action") for rule in rules))

    def test_permission_mode_guard_handles_variable_execution_tools(self) -> None:
        wrapper = load_wrapper_module()

        accepted, accepted_rules = wrapper.wrap_generation_row({
            "task_preview": "Goal: x Permission mode: ACCEPT_EDITS Planner strategy: audit_astar",
            "generated_text": json.dumps({
                "tool_name": "file_writer",
                "model_tier": "medium",
                "context_policy": "progressive_context+memory_retrieval+success_criteria",
                "executor_kind": "workspace_tool",
                "verifier_next_action": "replan",
            }),
        })
        dont_ask, dont_ask_rules = wrapper.wrap_generation_row({
            "task_preview": "Goal: x Permission mode: DONT_ASK Planner strategy: audit_reflexion",
            "generated_text": json.dumps({
                "tool_name": "mcp_tool_runner",
                "model_tier": "medium",
                "context_policy": "progressive_context+memory_retrieval+success_criteria",
                "executor_kind": "external_tool",
                "verifier_next_action": "await_human",
            }),
        })

        self.assertEqual(accepted["architecture_policy"]["verifier_next_action"], "next_subtask")
        self.assertIn("permission_guard:next_action:ACCEPT_EDITS", accepted_rules)
        self.assertEqual(dont_ask["architecture_policy"]["verifier_next_action"], "replan")
        self.assertIn("permission_guard:next_action:DONT_ASK", dont_ask_rules)

    def test_cli_writes_wrapped_jsonl_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "generations.jsonl"
            output_path = root / "wrapped.jsonl"
            summary_path = root / "summary.json"
            _write_jsonl(
                input_path,
                [
                    {
                        "line_number": 1,
                        "generated_text": json.dumps({
                            "tool_name": "planner",
                            "model_tier": "medium",
                            "context_policy": "progressive_context+candidate_scores",
                            "executor_kind": "planner",
                            "verifier_next_action": "await_human",
                        }),
                    }
                ],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(WRAPPER_PATH),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--summary-output",
                    str(summary_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            row = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["architecture_policy"]["tool_name"], "planner")
            self.assertEqual(row["architecture_policy"]["model_tier"], "small")
            self.assertEqual(row["architecture_policy"]["executor_kind"], "read_only_agent")
            self.assertEqual(row["architecture_policy"]["verifier_next_action"], "next_subtask")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["rows_written"], 1)

    def test_cli_uses_eval_samples_prompt_for_permission_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "generations.jsonl"
            samples_path = root / "eval_samples.jsonl"
            output_path = root / "wrapped.jsonl"
            _write_jsonl(
                input_path,
                [
                    {
                        "line_number": 7,
                        "task_preview": "Goal: long text without permission mode",
                        "generated_text": json.dumps({
                            "tool_name": "mcp_tool_runner",
                            "model_tier": "medium",
                            "context_policy": "progressive_context+memory_retrieval+success_criteria",
                            "executor_kind": "external_tool",
                            "verifier_next_action": "await_human",
                        }),
                    }
                ],
            )
            _write_jsonl(
                samples_path,
                [
                    {
                        "line_number": 7,
                        "prompt": "Goal: x\nPermission mode: DONT_ASK\nPlanner strategy: audit_reflexion\n",
                    }
                ],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(WRAPPER_PATH),
                    "--input",
                    str(input_path),
                    "--eval-samples",
                    str(samples_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            row = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["architecture_policy"]["verifier_next_action"], "replan")
            self.assertIn("permission_guard:next_action:DONT_ASK", row["wrapper_rules"])


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
