#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSITIONS = AGENT_PLANNER_ROOT / "rewards" / "openclaw_architecture_transitions.jsonl"
DEFAULT_SFT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_sft.jsonl"
DEFAULT_TRAIN = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_balanced_train.jsonl"
DEFAULT_HELDOUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_balanced_holdout.jsonl"
DEFAULT_PAIRS = AGENT_PLANNER_ROOT / "rewards" / "openclaw_architecture_counterfactual_pairs.jsonl"
ASSISTANT_MARKER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"
MODEL_TIERS = ("small", "medium", "large")
NEXT_ACTIONS = ("next_subtask", "await_human", "replan")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Balance OpenClaw architecture SFT rows and build counterfactual preference pairs.",
    )
    parser.add_argument("--transitions", type=Path, default=DEFAULT_TRANSITIONS)
    parser.add_argument("--sft", type=Path, default=DEFAULT_SFT)
    parser.add_argument("--train-output", type=Path, default=DEFAULT_TRAIN)
    parser.add_argument("--heldout-output", type=Path, default=DEFAULT_HELDOUT)
    parser.add_argument("--pair-output", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--target-per-stratum", type=int, default=800)
    parser.add_argument("--max-per-stratum", type=int, default=1200)
    parser.add_argument("--max-duplicates-per-row", type=int, default=5)
    parser.add_argument("--heldout-ratio", type=float, default=0.1)
    parser.add_argument("--min-reward", type=float, default=0.0)
    parser.add_argument("--pair-limit", type=int, default=12000)
    parser.add_argument(
        "--source-mode",
        action="append",
        default=[],
        help="Optional source schema_mode allow-list, e.g. architecture or legacy. Can be repeated.",
    )
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    stats = balance_architecture_data(
        transitions_path=args.transitions,
        sft_path=args.sft,
        train_output=args.train_output,
        heldout_output=args.heldout_output,
        pair_output=args.pair_output,
        target_per_stratum=args.target_per_stratum,
        max_per_stratum=args.max_per_stratum,
        max_duplicates_per_row=args.max_duplicates_per_row,
        heldout_ratio=args.heldout_ratio,
        min_reward=args.min_reward,
        pair_limit=args.pair_limit,
        source_modes=args.source_mode,
        seed=args.seed,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def balance_architecture_data(
    *,
    transitions_path: Path,
    sft_path: Path,
    train_output: Path,
    heldout_output: Path,
    pair_output: Path,
    target_per_stratum: int = 800,
    max_per_stratum: int = 1200,
    max_duplicates_per_row: int = 5,
    heldout_ratio: float = 0.1,
    min_reward: float = 0.0,
    pair_limit: int = 12000,
    source_modes: list[str] | None = None,
    seed: int = 17,
) -> dict[str, Any]:
    source_mode_allowlist = set(source_modes or [])
    transitions = {
        str(row.get("transition_id")): row
        for row in _iter_jsonl(transitions_path)
        if row.get("transition_id")
    }
    sft_rows = list(_iter_jsonl(sft_path))
    joined: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    for row in sft_rows:
        transition_id = str(row.get("transition_id") or "")
        transition = transitions.get(transition_id)
        if transition is None:
            dropped["missing_transition"] += 1
            continue
        source_mode = str((transition.get("source") or {}).get("schema_mode") or "")
        if source_mode_allowlist and source_mode not in source_mode_allowlist:
            dropped[f"source_mode:{source_mode or 'missing'}"] += 1
            continue
        if float(transition.get("reward") or 0.0) < min_reward:
            dropped["below_min_reward"] += 1
            continue
        split = _split_for_id(transition_id, heldout_ratio, seed)
        joined.append({
            "sft": row,
            "transition": transition,
            "stratum": _stratum(transition),
            "split": split,
            "sort_key": _stable_float(f"{seed}:{transition_id}"),
        })

    train_candidates = [item for item in joined if item["split"] == "train"]
    heldout_items = [item for item in joined if item["split"] == "heldout"]
    balanced_train = _balance_train_items(
        train_candidates,
        target_per_stratum=target_per_stratum,
        max_per_stratum=max_per_stratum,
        max_duplicates_per_row=max_duplicates_per_row,
    )
    pair_rows = _build_preference_pairs(
        train_candidates,
        pair_limit=pair_limit,
        seed=seed,
    )

    train_output.parent.mkdir(parents=True, exist_ok=True)
    heldout_output.parent.mkdir(parents=True, exist_ok=True)
    pair_output.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(train_output, [item["row"] for item in balanced_train])
    _write_jsonl(heldout_output, [_with_balance_metadata(item["sft"], item, duplicate_index=0) for item in heldout_items])
    _write_jsonl(pair_output, pair_rows)

    stats = {
        "transitions": str(transitions_path),
        "sft": str(sft_path),
        "train_output": str(train_output),
        "heldout_output": str(heldout_output),
        "pair_output": str(pair_output),
        "input_transitions": len(transitions),
        "input_sft_rows": len(sft_rows),
        "joined_rows": len(joined),
        "train_source_rows": len(train_candidates),
        "heldout_rows": len(heldout_items),
        "balanced_train_rows": len(balanced_train),
        "preference_pairs": len(pair_rows),
        "target_per_stratum": target_per_stratum,
        "max_per_stratum": max_per_stratum,
        "max_duplicates_per_row": max_duplicates_per_row,
        "heldout_ratio": heldout_ratio,
        "min_reward": min_reward,
        "source_modes": sorted(source_mode_allowlist),
        "dropped": dict(sorted(dropped.items())),
        "train_strata_before": _strata_counts(train_candidates),
        "train_strata_after": _row_strata_counts(balanced_train),
        "heldout_strata": _strata_counts(heldout_items),
        "pair_reasons": dict(sorted(Counter(row["selection_reason"] for row in pair_rows).items())),
    }
    summary_path = train_output.with_suffix(train_output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


def _balance_train_items(
    items: list[dict[str, Any]],
    *,
    target_per_stratum: int,
    max_per_stratum: int,
    max_duplicates_per_row: int,
) -> list[dict[str, Any]]:
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        strata[item["stratum"]].append(item)

    balanced: list[dict[str, Any]] = []
    for stratum, stratum_items in sorted(strata.items()):
        ordered = sorted(
            stratum_items,
            key=lambda item: (
                -float(item["transition"].get("reward") or 0.0),
                item["sort_key"],
            ),
        )
        natural_limit = min(len(ordered), max_per_stratum)
        selected = ordered[:natural_limit]
        for item in selected:
            balanced.append({
                "row": _with_balance_metadata(item["sft"], item, duplicate_index=0),
                "stratum": stratum,
            })
        if not selected:
            continue
        duplicate_count = 0
        duplicate_index = 1
        while (
            len(selected) + duplicate_count < target_per_stratum
            and duplicate_index <= max_duplicates_per_row
        ):
            for item in selected:
                if len(selected) + duplicate_count >= target_per_stratum:
                    break
                duplicate_count += 1
                balanced.append({
                    "row": _with_balance_metadata(item["sft"], item, duplicate_index=duplicate_index),
                    "stratum": stratum,
                })
            duplicate_index += 1
    return sorted(
        balanced,
        key=lambda item: (
            item["stratum"],
            item["row"].get("balance_duplicate_index", 0),
            item["row"].get("transition_id", ""),
        ),
    )


def _build_preference_pairs(
    items: list[dict[str, Any]],
    *,
    pair_limit: int,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = sorted(
        items,
        key=lambda item: (
            _pair_priority(item),
            item["sort_key"],
        ),
    )
    for item in ordered:
        split = _split_sft_text(item["sft"].get("text", ""))
        if split is None:
            continue
        prompt, target_text = split
        target = _parse_target(target_text)
        if not isinstance(target, dict):
            continue
        rejected, reason = _counterfactual_rejection(target, item["transition"], seed=seed)
        if rejected is None:
            continue
        chosen = _compact_json(target) + IM_END + "\n"
        rejected_text = _compact_json(rejected) + IM_END + "\n"
        if chosen == rejected_text:
            continue
        transition = item["transition"]
        rows.append({
            "source": "openclaw_architecture_counterfactual_pair",
            "transition_id": transition.get("transition_id"),
            "episode_id": transition.get("episode_id"),
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected_text,
            "selection_reason": reason,
            "reward": transition.get("reward"),
            "stratum": item["stratum"],
            "chosen_verifier": transition.get("verifier"),
            "source_mode": (transition.get("source") or {}).get("schema_mode"),
        })
        if pair_limit and len(rows) >= pair_limit:
            break
    return rows


def _counterfactual_rejection(target: dict[str, Any], transition: dict[str, Any], *, seed: int) -> tuple[dict[str, Any] | None, str]:
    architecture = target.get("architecture")
    verifier = target.get("verifier")
    if not isinstance(architecture, dict) or not isinstance(verifier, dict):
        return None, "missing_architecture"

    rejected = json.loads(json.dumps(target, ensure_ascii=False))
    rejected_arch = rejected["architecture"]
    rejected_verifier = rejected["verifier"]
    current_next = str(verifier.get("next_action") or "next_subtask")
    current_tier = str(architecture.get("model_tier") or "small")
    risk_level = str(architecture.get("risk_level") or "low")
    source_mode = str((transition.get("source") or {}).get("schema_mode") or "")
    selector = int(_stable_float(f"{seed}:{transition.get('transition_id')}") * 1000) % 3

    if current_next in {"await_human", "replan"}:
        rejected_verifier["next_action"] = "next_subtask"
        rejected_arch["expected_next_action"] = "next_subtask"
        rejected["analysis"] = f"Unsafe shortcut: bypass verifier branch and continue despite {current_next}."
        rejected["plan"] = "Incorrectly continue to the next subtask without respecting verifier feedback."
        _rewrite_command_next_action(rejected, "next_subtask")
        return rejected, f"counterfactual_next_action:{current_next}->next_subtask"

    if risk_level in {"medium", "high"} and current_tier != "small":
        rejected_arch["model_tier"] = "small"
        rejected["analysis"] = f"Under-route {risk_level} risk work to the small model."
        rejected["plan"] = "Incorrectly choose the fastest model even though richer reasoning is required."
        _rewrite_command_model_tier(rejected, "small")
        return rejected, f"counterfactual_model_tier:{current_tier}->small"

    if current_tier == "small" and selector == 0:
        rejected_arch["model_tier"] = "large"
        rejected["analysis"] = "Over-route low-risk planning work to the large model."
        rejected["plan"] = "Incorrectly spend large-model budget on a low-risk subtask."
        _rewrite_command_model_tier(rejected, "large")
        return rejected, "counterfactual_model_tier:small->large"

    if source_mode == "legacy" or selector == 1:
        rejected_arch["context_policy"] = "missing_context"
        rejected_arch["memory_queries"] = []
        rejected["analysis"] = "Drop context and memory retrieval from the architecture decision."
        rejected["plan"] = "Incorrectly execute without the Architect context contract."
        _rewrite_command_context_policy(rejected, "missing_context")
        return rejected, "counterfactual_context_policy:missing_context"

    rejected_verifier["next_action"] = "replan"
    rejected_arch["expected_next_action"] = "replan"
    rejected["analysis"] = "Force unnecessary replan despite completed verifier evidence."
    rejected["plan"] = "Incorrectly stop progress after a valid verifier result."
    _rewrite_command_next_action(rejected, "replan")
    return rejected, "counterfactual_next_action:next_subtask->replan"


def _rewrite_command_model_tier(target: dict[str, Any], model_tier: str) -> None:
    _rewrite_command_arg(target, "--model-tier", model_tier)


def _rewrite_command_context_policy(target: dict[str, Any], context_policy: str) -> None:
    _rewrite_command_arg(target, "--context-policy", context_policy)


def _rewrite_command_next_action(target: dict[str, Any], next_action: str) -> None:
    _rewrite_command_arg(target, "--next-action", next_action)


def _rewrite_command_arg(target: dict[str, Any], flag: str, value: str) -> None:
    commands = target.get("commands")
    if not isinstance(commands, list) or not commands:
        return
    command = commands[0]
    if not isinstance(command, dict) or not isinstance(command.get("keystrokes"), str):
        return
    parts = command["keystrokes"].split()
    for index, part in enumerate(parts):
        if part == flag and index + 1 < len(parts):
            parts[index + 1] = value
            command["keystrokes"] = " ".join(parts)
            return


def _with_balance_metadata(row: dict[str, Any], item: dict[str, Any], *, duplicate_index: int) -> dict[str, Any]:
    transition = item["transition"]
    action = transition.get("action", {}).get("planner_action", {})
    verifier = transition.get("verifier", {})
    output = dict(row)
    output.update({
        "transition_id": transition.get("transition_id"),
        "episode_id": transition.get("episode_id"),
        "balance_stratum": item["stratum"],
        "balance_duplicate_index": duplicate_index,
        "sample_weight": _sample_weight(transition, duplicate_index),
        "model_tier": action.get("model_tier"),
        "next_action": verifier.get("next_action"),
        "source_mode": (transition.get("source") or {}).get("schema_mode"),
    })
    return output


def _sample_weight(transition: dict[str, Any], duplicate_index: int) -> float:
    reward = float(transition.get("reward") or 0.0)
    base = max(0.25, min(1.25, reward))
    if duplicate_index:
        return round(base * 0.75, 4)
    return round(base, 4)


def _stratum(transition: dict[str, Any]) -> str:
    action = transition.get("action", {}).get("planner_action", {})
    verifier = transition.get("verifier") or {}
    source = transition.get("source") or {}
    source_mode = str(source.get("schema_mode") or "unknown")
    model_tier = str(action.get("model_tier") or "unknown")
    next_action = str(verifier.get("next_action") or action.get("expected_next_action") or "unknown")
    return f"{source_mode}|tier={model_tier}|next={next_action}"


def _split_for_id(identifier: str, heldout_ratio: float, seed: int) -> str:
    if heldout_ratio <= 0:
        return "train"
    if heldout_ratio >= 1:
        return "heldout"
    return "heldout" if _stable_float(f"{seed}:split:{identifier}") < heldout_ratio else "train"


def _pair_priority(item: dict[str, Any]) -> tuple[int, float]:
    transition = item["transition"]
    verifier = transition.get("verifier") or {}
    action = transition.get("action", {}).get("planner_action", {})
    next_action = str(verifier.get("next_action") or "")
    model_tier = str(action.get("model_tier") or "")
    rare_rank = 0
    if next_action in {"await_human", "replan"}:
        rare_rank -= 4
    if model_tier in {"medium", "large"}:
        rare_rank -= 2
    if (transition.get("source") or {}).get("schema_mode") == "architecture":
        rare_rank -= 1
    return rare_rank, -float(transition.get("reward") or 0.0)


def _strata_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item["stratum"] for item in items)
    return dict(sorted(counts.items()))


def _row_strata_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item["stratum"] for item in items)
    return dict(sorted(counts.items()))


def _split_sft_text(text: str) -> tuple[str, str] | None:
    marker_index = text.rfind(ASSISTANT_MARKER)
    if marker_index < 0:
        return None
    prompt = text[: marker_index + len(ASSISTANT_MARKER)]
    completion = text[marker_index + len(ASSISTANT_MARKER):]
    if completion.endswith(IM_END + "\n"):
        completion = completion[: -len(IM_END + "\n")]
    elif completion.endswith(IM_END):
        completion = completion[: -len(IM_END)]
    return prompt, completion.strip()


def _parse_target(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _stable_float(text: str) -> float:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}") from exc


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
