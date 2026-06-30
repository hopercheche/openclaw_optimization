import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "validate_openclaw_architecture_data.py"
)
IM_END = "<|im_end|>"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("validate_openclaw_architecture_data", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitectureValidatorTest(unittest.TestCase):
    def test_validates_clean_architecture_dataset_and_cli_summary(self) -> None:
        validator = load_validator_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _dataset_paths(root)
            transitions = [
                _transition("t1", model_tier="small", next_action="next_subtask"),
                _transition("t2", model_tier="small", next_action="next_subtask"),
                _transition("t3", model_tier="small", next_action="next_subtask"),
            ]
            _write_jsonl(paths["transitions"], transitions)
            _write_jsonl(paths["sft"], [_sft_row(row) for row in transitions])
            _write_jsonl(paths["train"], [_balanced_row(_sft_row(transitions[0])), _balanced_row(_sft_row(transitions[1]))])
            _write_jsonl(paths["heldout"], [_balanced_row(_sft_row(transitions[2]))])
            _write_jsonl(paths["pairs"], [_pair_row(transitions[0])])

            summary = validator.validate_architecture_data(
                transitions_path=paths["transitions"],
                sft_path=paths["sft"],
                balanced_train_path=paths["train"],
                heldout_path=paths["heldout"],
                pairs_path=paths["pairs"],
                min_train_stratum_count=2,
                min_heldout_stratum_count=1,
            )

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["issue_count"], 0)
            self.assertEqual(summary["counts"]["balanced_train"], 2)
            self.assertEqual(
                summary["strata"]["balanced_train"],
                {"architecture|tier=small|next=next_subtask": 2},
            )

            summary_path = root / "summary.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR_PATH),
                    "--profile",
                    "native",
                    "--transitions",
                    str(paths["transitions"]),
                    "--sft",
                    str(paths["sft"]),
                    "--train",
                    str(paths["train"]),
                    "--heldout",
                    str(paths["heldout"]),
                    "--pairs",
                    str(paths["pairs"]),
                    "--min-train-stratum-count",
                    "2",
                    "--min-heldout-stratum-count",
                    "1",
                    "--summary-output",
                    str(summary_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(summary_path.exists())
            cli_summary = json.loads(result.stdout)
            file_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertTrue(cli_summary["ok"])
            self.assertEqual(file_summary["counts"]["pairs"], 1)

    def test_native_profile_resolves_native_outputs_with_explicit_overrides(self) -> None:
        validator = load_validator_module()

        native_paths = validator.resolve_architecture_data_paths(profile="native")

        self.assertEqual(native_paths["transitions"], validator.DEFAULT_TRANSITIONS)
        self.assertEqual(native_paths["sft"], validator.DEFAULT_SFT)
        self.assertEqual(native_paths["balanced_train"], validator.DEFAULT_NATIVE_TRAIN)
        self.assertEqual(native_paths["heldout"], validator.DEFAULT_NATIVE_HELDOUT)
        self.assertEqual(native_paths["pairs"], validator.DEFAULT_NATIVE_PAIRS)

        override_train = Path("/tmp/native-train.jsonl")
        override_pairs = Path("/tmp/native-pairs.jsonl")
        mixed_paths = validator.resolve_architecture_data_paths(
            profile="native",
            train_path=override_train,
            pairs_path=override_pairs,
        )

        self.assertEqual(mixed_paths["balanced_train"], override_train)
        self.assertEqual(mixed_paths["pairs"], override_pairs)
        self.assertEqual(mixed_paths["heldout"], validator.DEFAULT_NATIVE_HELDOUT)

    def test_reports_alignment_json_command_strata_and_pair_failures(self) -> None:
        validator = load_validator_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _dataset_paths(root)
            transition = _transition("t1", model_tier="medium", next_action="await_human")
            _write_jsonl(paths["transitions"], [transition])
            _write_jsonl(paths["sft"], [
                _sft_row(transition, command={"keystrokes": "", "duration": "bad"}),
                {
                    "transition_id": "missing-transition",
                    "text": (
                        "<|im_start|>system\nReturn JSON.\n<|im_end|>\n"
                        "<|im_start|>user\nGoal\n<|im_end|>\n"
                        "<|im_start|>assistant\n{\"commands\":["
                    ),
                },
            ])
            _write_jsonl(paths["train"], [_balanced_row(_sft_row(transition))])
            _write_jsonl(paths["heldout"], [])
            _write_jsonl(paths["pairs"], [
                _pair_row(transition, prompt="", rejected_same_as_chosen=True),
            ])

            summary = validator.validate_architecture_data(
                transitions_path=paths["transitions"],
                sft_path=paths["sft"],
                balanced_train_path=paths["train"],
                heldout_path=paths["heldout"],
                pairs_path=paths["pairs"],
                min_train_stratum_count=2,
                min_heldout_stratum_count=0,
            )

            self.assertFalse(summary["ok"])
            issue_codes = set(summary["issue_codes"])
            self.assertIn("sft_transition_not_found", issue_codes)
            self.assertIn("sft.assistant_json_invalid", issue_codes)
            self.assertIn("sft.assistant_command_bad_keystrokes", issue_codes)
            self.assertIn("sft.assistant_command_bad_duration", issue_codes)
            self.assertIn("balanced_train_stratum_below_min", issue_codes)
            self.assertIn("pairs_prompt_empty", issue_codes)
            self.assertIn("pairs_chosen_rejected_equal", issue_codes)


def _dataset_paths(root: Path) -> dict[str, Path]:
    return {
        "transitions": root / "rewards" / "transitions.jsonl",
        "sft": root / "processed" / "sft.jsonl",
        "train": root / "processed" / "balanced_train.jsonl",
        "heldout": root / "processed" / "heldout.jsonl",
        "pairs": root / "rewards" / "pairs.jsonl",
    }


def _transition(transition_id: str, *, model_tier: str, next_action: str) -> dict:
    return {
        "schema": "agent_lightning_transition_v0",
        "domain_schema": "openclaw_architecture_transition_v0",
        "episode_id": "episode",
        "transition_id": transition_id,
        "state": {"goal": "Validate architecture data."},
        "action": {
            "planner_action": {
                "task_id": transition_id,
                "tool_name": "planner",
                "action": "Validate data.",
                "model_tier": model_tier,
                "risk_level": "low",
                "context_policy": "progressive_context",
                "executor_kind": "workspace_tool",
                "expected_next_action": next_action,
            },
        },
        "reward": 1.0,
        "verifier": {
            "outcome": "completed",
            "decision_behavior": "allow",
            "next_action": next_action,
        },
        "source": {"schema_mode": "architecture"},
    }


def _sft_row(transition: dict, command: dict | None = None) -> dict:
    target = _target(transition, command=command)
    return {
        "source": "openclaw_architecture_events",
        "format": "openclaw_architecture_sft_text",
        "episode_id": transition["episode_id"],
        "transition_id": transition["transition_id"],
        "reward": transition["reward"],
        "text": (
            "<|im_start|>system\nReturn JSON.\n<|im_end|>\n"
            "<|im_start|>user\nGoal: Validate architecture data.\n<|im_end|>\n"
            f"<|im_start|>assistant\n{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}{IM_END}\n"
        ),
    }


def _balanced_row(row: dict) -> dict:
    output = dict(row)
    output.update({
        "balance_stratum": "architecture|tier=small|next=next_subtask",
        "balance_duplicate_index": 0,
        "sample_weight": 1.0,
        "model_tier": "small",
        "next_action": "next_subtask",
        "source_mode": "architecture",
    })
    return output


def _pair_row(transition: dict, *, prompt: str | None = None, rejected_same_as_chosen: bool = False) -> dict:
    chosen = json.dumps(_target(transition), ensure_ascii=False, separators=(",", ":")) + IM_END + "\n"
    if rejected_same_as_chosen:
        rejected = chosen
    else:
        rejected_target = _target(transition)
        rejected_target["verifier"]["next_action"] = "replan"
        rejected_target["architecture"]["expected_next_action"] = "replan"
        rejected = json.dumps(rejected_target, ensure_ascii=False, separators=(",", ":")) + IM_END + "\n"
    return {
        "source": "openclaw_architecture_counterfactual_pair",
        "transition_id": transition["transition_id"],
        "episode_id": transition["episode_id"],
        "prompt": "<|im_start|>assistant\n" if prompt is None else prompt,
        "chosen": chosen,
        "rejected": rejected,
        "selection_reason": "test",
        "reward": transition["reward"],
        "stratum": "architecture|tier=small|next=next_subtask",
    }


def _target(transition: dict, command: dict | None = None) -> dict:
    action = dict(transition["action"]["planner_action"])
    verifier = dict(transition["verifier"])
    command = command or {
        "keystrokes": (
            "openclaw.plan_subtask "
            f"--tool {action['tool_name']} "
            f"--model-tier {action['model_tier']} "
            f"--context-policy {action['context_policy']} "
            f"--next-action {verifier['next_action']}"
        ),
        "duration": 1,
    }
    return {
        "analysis": "Choose a planner action.",
        "plan": "Validate the architecture data contract.",
        "commands": [command],
        "task_complete": False,
        "architecture": action,
        "verifier": verifier,
        "reward": transition["reward"],
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
