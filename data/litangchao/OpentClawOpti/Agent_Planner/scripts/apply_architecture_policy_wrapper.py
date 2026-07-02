#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from architecture_policy import wrap_file, wrap_generation_row  # noqa: E402,F401


DEFAULT_INPUT = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260630T_architecture_policy_compact_continue200_eval95"
    / "generations.jsonl"
)
DEFAULT_OUTPUT = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260630T_architecture_policy_compact_continue200_eval95"
    / "wrapped_generations.jsonl"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply serving-time canonicalization and tool priors to compact architecture-policy generations.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument(
        "--eval-samples",
        type=Path,
        default=None,
        help="Optional eval_samples.jsonl containing full prompts keyed by line_number.",
    )
    parser.add_argument(
        "--disable-next-action-priors",
        action="store_true",
        help="Do not apply deterministic next_action priors for tools that are always next_subtask in native data.",
    )
    args = parser.parse_args()

    stats = wrap_file(
        args.input,
        args.output,
        eval_samples_path=args.eval_samples,
        apply_next_action_priors=not args.disable_next_action_priors,
    )
    summary_output = args.summary_output or args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
