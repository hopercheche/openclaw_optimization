#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSITIONS = AGENT_PLANNER_ROOT / "rewards" / "openclaw_architecture_transitions.jsonl"
DEFAULT_SFT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_sft.jsonl"
DEFAULT_TRAIN = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_balanced_train.jsonl"
DEFAULT_HELDOUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_balanced_holdout.jsonl"
DEFAULT_PAIRS = AGENT_PLANNER_ROOT / "rewards" / "openclaw_architecture_counterfactual_pairs.jsonl"
DEFAULT_NATIVE_TRAIN = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_native_balanced_train.jsonl"
DEFAULT_NATIVE_HELDOUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_native_balanced_holdout.jsonl"
DEFAULT_NATIVE_PAIRS = AGENT_PLANNER_ROOT / "rewards" / "openclaw_architecture_native_counterfactual_pairs.jsonl"
PROFILE_DEFAULTS = {
    "default": {
        "transitions": DEFAULT_TRANSITIONS,
        "sft": DEFAULT_SFT,
        "balanced_train": DEFAULT_TRAIN,
        "heldout": DEFAULT_HELDOUT,
        "pairs": DEFAULT_PAIRS,
    },
    "native": {
        "transitions": DEFAULT_TRANSITIONS,
        "sft": DEFAULT_SFT,
        "balanced_train": DEFAULT_NATIVE_TRAIN,
        "heldout": DEFAULT_NATIVE_HELDOUT,
        "pairs": DEFAULT_NATIVE_PAIRS,
    },
}
ASSISTANT_MARKER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"


class ValidationContext:
    def __init__(self, *, max_issue_samples: int) -> None:
        self.max_issue_samples = max_issue_samples
        self.issue_count = 0
        self.issue_codes: Counter[str] = Counter()
        self.issue_samples: list[dict[str, Any]] = []

    def add_issue(self, *, code: str, path: Path | str, line: int | None, message: str) -> None:
        self.issue_count += 1
        self.issue_codes[code] += 1
        if len(self.issue_samples) >= self.max_issue_samples:
            return
        self.issue_samples.append({
            "code": code,
            "path": str(path),
            "line": line,
            "message": message,
        })


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate OpenClaw architecture transition, SFT, balanced, heldout, and pair data.",
    )
    parser.add_argument("--profile", choices=sorted(PROFILE_DEFAULTS), default="default")
    parser.add_argument("--transitions", type=Path, default=None)
    parser.add_argument("--sft", type=Path, default=None)
    parser.add_argument("--train", "--balanced-train", dest="balanced_train", type=Path, default=None)
    parser.add_argument("--heldout", type=Path, default=None)
    parser.add_argument("--pairs", type=Path, default=None)
    parser.add_argument("--min-train-stratum-count", type=int, default=1)
    parser.add_argument("--min-heldout-stratum-count", type=int, default=0)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--max-issue-samples", type=int, default=50)
    args = parser.parse_args()
    input_paths = resolve_architecture_data_paths(
        profile=args.profile,
        transitions_path=args.transitions,
        sft_path=args.sft,
        train_path=args.balanced_train,
        heldout_path=args.heldout,
        pairs_path=args.pairs,
    )

    summary = validate_architecture_data(
        transitions_path=input_paths["transitions"],
        sft_path=input_paths["sft"],
        balanced_train_path=input_paths["balanced_train"],
        heldout_path=input_paths["heldout"],
        pairs_path=input_paths["pairs"],
        min_train_stratum_count=args.min_train_stratum_count,
        min_heldout_stratum_count=args.min_heldout_stratum_count,
        max_issue_samples=args.max_issue_samples,
    )
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.summary_output is not None:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(output + "\n", encoding="utf-8")
    print(output)
    raise SystemExit(0 if summary["ok"] else 1)


def resolve_architecture_data_paths(
    *,
    profile: str = "default",
    transitions_path: Path | None = None,
    sft_path: Path | None = None,
    train_path: Path | None = None,
    heldout_path: Path | None = None,
    pairs_path: Path | None = None,
) -> dict[str, Path]:
    try:
        defaults = PROFILE_DEFAULTS[profile]
    except KeyError as exc:
        known = ", ".join(sorted(PROFILE_DEFAULTS))
        raise ValueError(f"Unknown architecture data profile {profile!r}; expected one of: {known}") from exc
    return {
        "transitions": transitions_path or defaults["transitions"],
        "sft": sft_path or defaults["sft"],
        "balanced_train": train_path or defaults["balanced_train"],
        "heldout": heldout_path or defaults["heldout"],
        "pairs": pairs_path or defaults["pairs"],
    }


def validate_architecture_data(
    *,
    transitions_path: Path,
    sft_path: Path,
    balanced_train_path: Path,
    heldout_path: Path,
    pairs_path: Path,
    min_train_stratum_count: int = 1,
    min_heldout_stratum_count: int = 0,
    max_issue_samples: int = 50,
) -> dict[str, Any]:
    ctx = ValidationContext(max_issue_samples=max_issue_samples)

    transition_rows = _load_jsonl(transitions_path, ctx)
    sft_rows = _load_jsonl(sft_path, ctx)
    train_rows = _load_jsonl(balanced_train_path, ctx)
    heldout_rows = _load_jsonl(heldout_path, ctx)
    pair_rows = _load_jsonl(pairs_path, ctx)

    transition_ids, transition_by_id = _validate_transitions(transition_rows, transitions_path, ctx)
    sft_ids = _validate_sft_like_rows(
        label="sft",
        rows=sft_rows,
        path=sft_path,
        transition_ids=transition_ids,
        ctx=ctx,
        allow_duplicate_ids=False,
    )
    train_ids = _validate_sft_like_rows(
        label="balanced_train",
        rows=train_rows,
        path=balanced_train_path,
        transition_ids=transition_ids,
        ctx=ctx,
        allow_duplicate_ids=True,
    )
    heldout_ids = _validate_sft_like_rows(
        label="heldout",
        rows=heldout_rows,
        path=heldout_path,
        transition_ids=transition_ids,
        ctx=ctx,
        allow_duplicate_ids=False,
    )
    pair_ids = _validate_pair_rows(
        rows=pair_rows,
        path=pairs_path,
        transition_ids=transition_ids,
        ctx=ctx,
    )

    _validate_id_set_alignment(
        source_label="transitions",
        source_ids=transition_ids,
        target_label="sft",
        target_ids=sft_ids,
        path=transitions_path,
        ctx=ctx,
    )
    _validate_subset_alignment("balanced_train", train_ids, "sft", sft_ids, balanced_train_path, ctx)
    _validate_subset_alignment("heldout", heldout_ids, "sft", sft_ids, heldout_path, ctx)
    _validate_subset_alignment("pairs", pair_ids, "sft", sft_ids, pairs_path, ctx)
    overlap = sorted(train_ids & heldout_ids)
    if overlap:
        ctx.add_issue(
            code="train_heldout_transition_overlap",
            path=balanced_train_path,
            line=None,
            message=f"{len(overlap)} transition_id values appear in both balanced_train and heldout; first={overlap[0]}",
        )

    train_strata = _validate_strata(
        label="balanced_train",
        rows=train_rows,
        path=balanced_train_path,
        transition_by_id=transition_by_id,
        minimum_count=min_train_stratum_count,
        ctx=ctx,
    )
    heldout_strata = _validate_strata(
        label="heldout",
        rows=heldout_rows,
        path=heldout_path,
        transition_by_id=transition_by_id,
        minimum_count=min_heldout_stratum_count,
        ctx=ctx,
    )

    alignment = {
        "transition_ids": len(transition_ids),
        "sft_ids": len(sft_ids),
        "balanced_train_ids": len(train_ids),
        "heldout_ids": len(heldout_ids),
        "pair_ids": len(pair_ids),
        "balanced_train_heldout_overlap": len(overlap),
    }
    return {
        "ok": ctx.issue_count == 0,
        "inputs": {
            "transitions": str(transitions_path),
            "sft": str(sft_path),
            "balanced_train": str(balanced_train_path),
            "heldout": str(heldout_path),
            "pairs": str(pairs_path),
        },
        "counts": {
            "transitions": len(transition_rows),
            "sft": len(sft_rows),
            "balanced_train": len(train_rows),
            "heldout": len(heldout_rows),
            "pairs": len(pair_rows),
        },
        "alignment": alignment,
        "minimums": {
            "min_train_stratum_count": min_train_stratum_count,
            "min_heldout_stratum_count": min_heldout_stratum_count,
        },
        "strata": {
            "balanced_train": train_strata,
            "heldout": heldout_strata,
        },
        "issue_count": ctx.issue_count,
        "issue_codes": dict(sorted(ctx.issue_codes.items())),
        "issues": ctx.issue_samples,
    }


def _load_jsonl(path: Path, ctx: ValidationContext) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        ctx.add_issue(code="missing_input", path=path, line=None, message="Input file does not exist.")
        return []
    if not path.is_file():
        ctx.add_issue(code="input_not_file", path=path, line=None, message="Input path is not a file.")
        return []

    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                ctx.add_issue(
                    code="invalid_jsonl",
                    path=path,
                    line=line_number,
                    message=f"Line is not valid JSON: {exc.msg}",
                )
                continue
            if not isinstance(payload, dict):
                ctx.add_issue(
                    code="invalid_row_type",
                    path=path,
                    line=line_number,
                    message="JSONL row must be an object.",
                )
                continue
            rows.append((line_number, payload))
    return rows


def _validate_transitions(
    rows: list[tuple[int, dict[str, Any]]],
    path: Path,
    ctx: ValidationContext,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for line_number, row in rows:
        transition_id = _row_transition_id(row)
        if transition_id is None:
            ctx.add_issue(
                code="transition_id_missing",
                path=path,
                line=line_number,
                message="Transition row is missing a non-empty transition_id.",
            )
            continue
        if transition_id in ids:
            ctx.add_issue(
                code="transition_id_duplicate",
                path=path,
                line=line_number,
                message=f"Duplicate transition_id: {transition_id}",
            )
            continue
        ids.add(transition_id)
        by_id[transition_id] = row
    return ids, by_id


def _validate_sft_like_rows(
    *,
    label: str,
    rows: list[tuple[int, dict[str, Any]]],
    path: Path,
    transition_ids: set[str],
    ctx: ValidationContext,
    allow_duplicate_ids: bool,
) -> set[str]:
    ids: set[str] = set()
    seen: set[str] = set()
    for line_number, row in rows:
        transition_id = _row_transition_id(row)
        if transition_id is None:
            ctx.add_issue(
                code=f"{label}_transition_id_missing",
                path=path,
                line=line_number,
                message="Row is missing a non-empty transition_id.",
            )
        else:
            ids.add(transition_id)
            if not allow_duplicate_ids and transition_id in seen:
                ctx.add_issue(
                    code=f"{label}_transition_id_duplicate",
                    path=path,
                    line=line_number,
                    message=f"Duplicate transition_id: {transition_id}",
                )
            seen.add(transition_id)
            if transition_id not in transition_ids:
                ctx.add_issue(
                    code=f"{label}_transition_not_found",
                    path=path,
                    line=line_number,
                    message=f"transition_id is absent from transitions: {transition_id}",
                )

        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            ctx.add_issue(
                code=f"{label}_assistant_text_missing",
                path=path,
                line=line_number,
                message="Row is missing non-empty text with an assistant completion.",
            )
            continue
        target = _parse_assistant_json(text, label, path, line_number, ctx)
        if target is not None:
            _validate_commands(target, f"{label}.assistant", path, line_number, ctx)
    return ids


def _validate_pair_rows(
    *,
    rows: list[tuple[int, dict[str, Any]]],
    path: Path,
    transition_ids: set[str],
    ctx: ValidationContext,
) -> set[str]:
    ids: set[str] = set()
    for line_number, row in rows:
        transition_id = _row_transition_id(row)
        if transition_id is None:
            ctx.add_issue(
                code="pairs_transition_id_missing",
                path=path,
                line=line_number,
                message="Pair row is missing a non-empty transition_id.",
            )
        else:
            ids.add(transition_id)
            if transition_id not in transition_ids:
                ctx.add_issue(
                    code="pairs_transition_not_found",
                    path=path,
                    line=line_number,
                    message=f"transition_id is absent from transitions: {transition_id}",
                )

        prompt = row.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            ctx.add_issue(
                code="pairs_prompt_empty",
                path=path,
                line=line_number,
                message="Preference pair prompt must be a non-empty string.",
            )

        chosen = row.get("chosen")
        rejected = row.get("rejected")
        if not isinstance(chosen, str) or not chosen.strip():
            ctx.add_issue(
                code="pairs_chosen_missing",
                path=path,
                line=line_number,
                message="Preference pair chosen completion must be non-empty.",
            )
            chosen_payload = None
        else:
            chosen_payload = _completion_payload(chosen)
        if not isinstance(rejected, str) or not rejected.strip():
            ctx.add_issue(
                code="pairs_rejected_missing",
                path=path,
                line=line_number,
                message="Preference pair rejected completion must be non-empty.",
            )
            rejected_payload = None
        else:
            rejected_payload = _completion_payload(rejected)

        if chosen_payload is not None and rejected_payload is not None and chosen_payload == rejected_payload:
            ctx.add_issue(
                code="pairs_chosen_rejected_equal",
                path=path,
                line=line_number,
                message="Preference pair chosen and rejected completions must differ.",
            )

        for field_name, payload in (("chosen", chosen_payload), ("rejected", rejected_payload)):
            if payload is None:
                continue
            target = _parse_json_payload(payload, f"pairs.{field_name}", path, line_number, ctx)
            if target is not None:
                _validate_commands(target, f"pairs.{field_name}", path, line_number, ctx)
    return ids


def _validate_id_set_alignment(
    *,
    source_label: str,
    source_ids: set[str],
    target_label: str,
    target_ids: set[str],
    path: Path,
    ctx: ValidationContext,
) -> None:
    missing = sorted(source_ids - target_ids)
    if missing:
        ctx.add_issue(
            code=f"{source_label}_missing_{target_label}",
            path=path,
            line=None,
            message=f"{len(missing)} {source_label} ids are absent from {target_label}; first={missing[0]}",
        )


def _validate_subset_alignment(
    source_label: str,
    source_ids: set[str],
    target_label: str,
    target_ids: set[str],
    path: Path,
    ctx: ValidationContext,
) -> None:
    missing = sorted(source_ids - target_ids)
    if missing:
        ctx.add_issue(
            code=f"{source_label}_missing_{target_label}",
            path=path,
            line=None,
            message=f"{len(missing)} {source_label} ids are absent from {target_label}; first={missing[0]}",
        )


def _validate_strata(
    *,
    label: str,
    rows: list[tuple[int, dict[str, Any]]],
    path: Path,
    transition_by_id: dict[str, dict[str, Any]],
    minimum_count: int,
    ctx: ValidationContext,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for line_number, row in rows:
        stratum = _row_stratum(row, transition_by_id)
        if stratum is None:
            ctx.add_issue(
                code=f"{label}_stratum_missing",
                path=path,
                line=line_number,
                message="Balanced row is missing balance_stratum and it cannot be derived.",
            )
            continue
        counts[stratum] += 1

    if minimum_count > 0 and rows and not counts:
        ctx.add_issue(
            code=f"{label}_strata_empty",
            path=path,
            line=None,
            message=f"{label} has rows but no countable strata.",
        )
    if minimum_count > 0 and not rows:
        ctx.add_issue(
            code=f"{label}_empty",
            path=path,
            line=None,
            message=f"{label} must contain at least one row when minimum_count={minimum_count}.",
        )
    for stratum, count in sorted(counts.items()):
        if count < minimum_count:
            ctx.add_issue(
                code=f"{label}_stratum_below_min",
                path=path,
                line=None,
                message=f"Stratum {stratum!r} has {count} rows; minimum is {minimum_count}.",
            )
    return dict(sorted(counts.items()))


def _parse_assistant_json(
    text: str,
    label: str,
    path: Path,
    line_number: int,
    ctx: ValidationContext,
) -> dict[str, Any] | None:
    marker_index = text.rfind(ASSISTANT_MARKER)
    if marker_index < 0:
        ctx.add_issue(
            code=f"{label}_assistant_marker_missing",
            path=path,
            line=line_number,
            message="Assistant marker is missing from text.",
        )
        return None
    payload = _completion_payload(text[marker_index + len(ASSISTANT_MARKER):])
    if not payload:
        ctx.add_issue(
            code=f"{label}_assistant_json_empty",
            path=path,
            line=line_number,
            message="Assistant completion is empty.",
        )
        return None
    return _parse_json_payload(payload, f"{label}.assistant", path, line_number, ctx)


def _parse_json_payload(
    payload: str,
    label: str,
    path: Path,
    line_number: int,
    ctx: ValidationContext,
) -> dict[str, Any] | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        ctx.add_issue(
            code=f"{label}_json_invalid",
            path=path,
            line=line_number,
            message=f"Assistant JSON is not parseable: {exc.msg}",
        )
        return None
    if not isinstance(parsed, dict):
        ctx.add_issue(
            code=f"{label}_json_not_object",
            path=path,
            line=line_number,
            message="Assistant completion must parse to one JSON object.",
        )
        return None
    return parsed


def _completion_payload(text: str) -> str:
    payload = text.strip()
    if payload.startswith(ASSISTANT_MARKER):
        payload = payload[len(ASSISTANT_MARKER):].strip()
    if IM_END in payload:
        payload = payload.split(IM_END, 1)[0].strip()
    return payload


def _validate_commands(
    target: dict[str, Any],
    label: str,
    path: Path,
    line_number: int,
    ctx: ValidationContext,
) -> None:
    commands = target.get("commands")
    if not isinstance(commands, list) or not commands:
        ctx.add_issue(
            code=f"{label}_commands_missing",
            path=path,
            line=line_number,
            message="Assistant JSON must include a non-empty commands list.",
        )
        return
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            ctx.add_issue(
                code=f"{label}_command_not_object",
                path=path,
                line=line_number,
                message=f"commands[{index}] must be an object.",
            )
            continue
        keystrokes = command.get("keystrokes")
        if not isinstance(keystrokes, str) or not keystrokes.strip():
            ctx.add_issue(
                code=f"{label}_command_bad_keystrokes",
                path=path,
                line=line_number,
                message=f"commands[{index}].keystrokes must be a non-empty string.",
            )
        duration = command.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            ctx.add_issue(
                code=f"{label}_command_bad_duration",
                path=path,
                line=line_number,
                message=f"commands[{index}].duration must be a positive number.",
            )


def _row_transition_id(row: dict[str, Any]) -> str | None:
    transition_id = row.get("transition_id")
    if not isinstance(transition_id, str) or not transition_id.strip():
        return None
    return transition_id


def _row_stratum(row: dict[str, Any], transition_by_id: dict[str, dict[str, Any]]) -> str | None:
    stratum = row.get("balance_stratum") or row.get("stratum")
    if isinstance(stratum, str) and stratum.strip():
        return stratum

    transition_id = _row_transition_id(row)
    transition = transition_by_id.get(transition_id or "")
    if transition is None:
        return None
    action = (transition.get("action") or {}).get("planner_action") or {}
    verifier = transition.get("verifier") or {}
    source = transition.get("source") or {}
    source_mode = row.get("source_mode") or source.get("schema_mode")
    model_tier = row.get("model_tier") or action.get("model_tier")
    next_action = row.get("next_action") or verifier.get("next_action") or action.get("expected_next_action")
    if not source_mode or not model_tier or not next_action:
        return None
    return f"{source_mode}|tier={model_tier}|next={next_action}"


if __name__ == "__main__":
    main()
