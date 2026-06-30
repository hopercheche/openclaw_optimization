import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BALANCER_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "balance_openclaw_architecture_data.py"
)


def load_balancer_module():
    spec = importlib.util.spec_from_file_location("balance_openclaw_architecture_data", BALANCER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitectureBalancerTest(unittest.TestCase):
    def test_balances_train_rows_and_builds_counterfactual_pairs(self) -> None:
        balancer = load_balancer_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transitions = root / "transitions.jsonl"
            sft = root / "sft.jsonl"
            train = root / "balanced_train.jsonl"
            heldout = root / "balanced_holdout.jsonl"
            pairs = root / "pairs.jsonl"
            transition_rows = [
                _transition("t1", model_tier="small", next_action="next_subtask", risk_level="low"),
                _transition("t2", model_tier="medium", next_action="await_human", risk_level="medium"),
            ]
            sft_rows = [_sft_row(row) for row in transition_rows]
            _write_jsonl(transitions, transition_rows)
            _write_jsonl(sft, sft_rows)

            stats = balancer.balance_architecture_data(
                transitions_path=transitions,
                sft_path=sft,
                train_output=train,
                heldout_output=heldout,
                pair_output=pairs,
                target_per_stratum=3,
                max_per_stratum=5,
                max_duplicates_per_row=2,
                heldout_ratio=0,
                min_reward=0,
                pair_limit=10,
                seed=3,
            )

            self.assertEqual(stats["joined_rows"], 2)
            self.assertEqual(stats["balanced_train_rows"], 6)
            train_rows = [json.loads(line) for line in train.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                {row["balance_stratum"] for row in train_rows},
                {
                    "architecture|tier=small|next=next_subtask",
                    "architecture|tier=medium|next=await_human",
                },
            )
            self.assertGreater(max(row["balance_duplicate_index"] for row in train_rows), 0)
            pair_rows = [json.loads(line) for line in pairs.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(pair_rows), 2)
            self.assertTrue(all(row["prompt"].endswith("<|im_start|>assistant\n") for row in pair_rows))
            self.assertTrue(all(row["chosen"] != row["rejected"] for row in pair_rows))
            self.assertIn(
                "counterfactual_next_action:await_human->next_subtask",
                {row["selection_reason"] for row in pair_rows},
            )

    def test_writes_heldout_without_duplication(self) -> None:
        balancer = load_balancer_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transitions = root / "transitions.jsonl"
            sft = root / "sft.jsonl"
            train = root / "balanced_train.jsonl"
            heldout = root / "balanced_holdout.jsonl"
            pairs = root / "pairs.jsonl"
            transition_rows = [
                _transition(f"t{index}", model_tier="small", next_action="next_subtask", risk_level="low")
                for index in range(12)
            ]
            _write_jsonl(transitions, transition_rows)
            _write_jsonl(sft, [_sft_row(row) for row in transition_rows])

            stats = balancer.balance_architecture_data(
                transitions_path=transitions,
                sft_path=sft,
                train_output=train,
                heldout_output=heldout,
                pair_output=pairs,
                target_per_stratum=3,
                max_per_stratum=5,
                max_duplicates_per_row=1,
                heldout_ratio=0.5,
                min_reward=0,
                pair_limit=10,
                seed=11,
            )

            heldout_rows = [json.loads(line) for line in heldout.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(stats["heldout_rows"], len(heldout_rows))
            self.assertTrue(all(row["balance_duplicate_index"] == 0 for row in heldout_rows))

    def test_filters_by_source_mode(self) -> None:
        balancer = load_balancer_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transitions = root / "transitions.jsonl"
            sft = root / "sft.jsonl"
            train = root / "balanced_train.jsonl"
            heldout = root / "balanced_holdout.jsonl"
            pairs = root / "pairs.jsonl"
            architecture_row = _transition(
                "t_arch",
                model_tier="small",
                next_action="next_subtask",
                risk_level="low",
                source_mode="architecture",
            )
            legacy_row = _transition(
                "t_legacy",
                model_tier="small",
                next_action="next_subtask",
                risk_level="low",
                source_mode="legacy",
            )
            _write_jsonl(transitions, [architecture_row, legacy_row])
            _write_jsonl(sft, [_sft_row(architecture_row), _sft_row(legacy_row)])

            stats = balancer.balance_architecture_data(
                transitions_path=transitions,
                sft_path=sft,
                train_output=train,
                heldout_output=heldout,
                pair_output=pairs,
                target_per_stratum=1,
                max_per_stratum=1,
                max_duplicates_per_row=1,
                heldout_ratio=0,
                min_reward=0,
                pair_limit=10,
                source_modes=["architecture"],
                seed=3,
            )

            self.assertEqual(stats["joined_rows"], 1)
            self.assertEqual(stats["dropped"], {"source_mode:legacy": 1})
            train_rows = [json.loads(line) for line in train.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(train_rows[0]["source_mode"], "architecture")


def _transition(
    transition_id: str,
    *,
    model_tier: str,
    next_action: str,
    risk_level: str,
    source_mode: str = "architecture",
) -> dict:
    return {
        "schema": "agent_lightning_transition_v0",
        "domain_schema": "openclaw_architecture_transition_v0",
        "episode_id": "episode",
        "transition_id": transition_id,
        "state": {
            "goal": "Optimize planner architecture.",
            "permission_mode": "ACCEPT_EDITS",
            "planner_strategy": "audit_reflexion",
        },
        "action": {
            "planner_action": {
                "task_id": transition_id,
                "tool_name": "planner",
                "action": "Build the next subtask.",
                "model_tier": model_tier,
                "risk_level": risk_level,
                "context_policy": "progressive_context",
                "expected_next_action": next_action,
            }
        },
        "reward": 1.0,
        "verifier": {
            "outcome": "completed" if next_action == "next_subtask" else "requires_human",
            "decision_behavior": "allow" if next_action == "next_subtask" else "ask",
            "next_action": next_action,
        },
        "source": {
            "schema_mode": source_mode,
        },
    }


def _sft_row(transition: dict) -> dict:
    action = transition["action"]["planner_action"]
    verifier = transition["verifier"]
    target = {
        "analysis": "Pick an architecture action.",
        "plan": "Use the selected tier and verifier action.",
        "commands": [
            {
                "keystrokes": (
                    "openclaw.plan_subtask "
                    f"--tool {action['tool_name']} "
                    f"--model-tier {action['model_tier']} "
                    f"--context-policy {action['context_policy']} "
                    f"--next-action {verifier['next_action']}"
                ),
                "duration": 1,
            }
        ],
        "task_complete": False,
        "architecture": action,
        "verifier": verifier,
    }
    text = (
        "<|im_start|>system\nReturn JSON.\n<|im_end|>\n"
        "<|im_start|>user\nGoal: Optimize planner architecture.\n<|im_end|>\n"
        f"<|im_start|>assistant\n{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}<|im_end|>\n"
    )
    return {
        "source": "openclaw_architecture_events",
        "transition_id": transition["transition_id"],
        "episode_id": transition["episode_id"],
        "reward": transition["reward"],
        "text": text,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
