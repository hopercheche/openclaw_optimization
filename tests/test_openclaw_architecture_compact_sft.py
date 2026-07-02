import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPACT_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "build_compact_architecture_policy_sft.py"
)
EVAL_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "evaluate_architecture_policy.py"
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitectureCompactSftTest(unittest.TestCase):
    def test_converts_full_sft_to_compact_policy_target(self) -> None:
        compact = load_module(COMPACT_PATH, "build_compact_architecture_policy_sft")
        evaluator = load_module(EVAL_PATH, "evaluate_architecture_policy")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "full.jsonl"
            output_path = root / "compact.jsonl"
            _write_jsonl(input_path, [_full_sft_row()])

            stats = compact.convert_file(input_path, output_path, target_mode="compact")

            self.assertEqual(stats["rows_seen"], 1)
            self.assertEqual(stats["rows_written"], 1)
            converted = json.loads(output_path.read_text(encoding="utf-8"))
            assistant_text, _ = evaluator.assistant_text_from_row(converted)
            parsed = evaluator.parse_assistant_json(assistant_text)
            self.assertEqual(
                parsed,
                {
                    "task_id": "task-1",
                    "tool_name": "risk_model",
                    "model_tier": "small",
                    "context_policy": "permission_policy+risk_terms",
                    "executor_kind": "policy_gate",
                    "verifier_next_action": "next_subtask",
                },
            )
            metrics = evaluator.evaluate_file(output_path, normalize_compact=True)
            self.assertEqual(metrics["overall"]["schema_valid_rate"], 1.0)
            self.assertEqual(metrics["overall"]["normalized_count"], 1)
            self.assertEqual(metrics["overall"]["model_tier_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["next_action_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["context_policy_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["executor_kind_accuracy"], 1.0)

    def test_wrapped_mode_preserves_full_architecture_schema(self) -> None:
        compact = load_module(COMPACT_PATH, "build_compact_architecture_policy_sft")
        evaluator = load_module(EVAL_PATH, "evaluate_architecture_policy")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "full.jsonl"
            output_path = root / "wrapped.jsonl"
            _write_jsonl(input_path, [_full_sft_row()])

            stats = compact.convert_file(input_path, output_path, target_mode="wrapped")

            self.assertEqual(stats["rows_written"], 1)
            metrics = evaluator.evaluate_file(output_path)
            self.assertEqual(metrics["overall"]["schema_valid_rate"], 1.0)
            self.assertEqual(metrics["overall"]["normalized_count"], 0)
            self.assertEqual(metrics["overall"]["executor_kind_accuracy"], 1.0)


def _full_sft_row() -> dict:
    target = {
        "analysis": "Select risk_model.",
        "plan": "Use the permission policy.",
        "commands": [
            {
                "keystrokes": (
                    "openclaw.plan_subtask --tool risk_model --model-tier small "
                    "--context-policy permission_policy+risk_terms --next-action next_subtask"
                ),
                "duration": 1,
            }
        ],
        "task_complete": True,
        "architecture": {
            "task_id": "task-1",
            "tool_name": "risk_model",
            "action": "Classify permission risk.",
            "model_tier": "small",
            "risk_level": "low",
            "context_policy": "permission_policy+risk_terms",
            "memory_queries": ["tool:risk_model"],
            "success_criteria": ["permission decision is recorded"],
            "executor_kind": "policy_gate",
            "expected_next_action": "next_subtask",
        },
        "verifier": {
            "outcome": "completed",
            "decision_behavior": "allow",
            "next_action": "next_subtask",
            "evidence_complete": True,
            "residual_risk": 0,
            "critique": "Looks good.",
        },
    }
    text = (
        "<|im_start|>system\nReturn JSON.\n<|im_end|>\n"
        "<|im_start|>user\nGoal: review permissions.\n<|im_end|>\n"
        f"<|im_start|>assistant\n{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}<|im_end|>\n"
    )
    return {
        "source": "openclaw_architecture_events",
        "format": "openclaw_architecture_sft_text",
        "transition_id": "transition-1",
        "reward": 1.0,
        "text": text,
        "balance_stratum": "architecture|tier=small|next=next_subtask",
        "source_mode": "architecture",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
