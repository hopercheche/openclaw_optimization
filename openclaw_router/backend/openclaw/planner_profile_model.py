from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "planner_models" / "profile_policy_model.json"
MODEL_ENV_VAR = "OPENCLAW_PLANNER_PROFILE_MODEL"
DISABLE_ENV_VAR = "OPENCLAW_DISABLE_PLANNER_PROFILE_MODEL"

EXECUTION_TOOL_ORDER = [
    "mcp_tool_runner",
    "mobile_cli_runner",
    "mobile_gui_runner",
    "file_writer",
    "command_runner",
    "deploy_runner",
]


@dataclass(slots=True)
class PlannerProfileExample:
    goal: str
    planner_profile: str
    execution_tools: list[str]
    policy_mode: str
    source_family: str = ""
    split: str = "dev"


@dataclass(slots=True)
class ProfilePrediction:
    planner_profile: str = ""
    execution_tools: list[str] | None = None
    policy_mode: str = "act"
    profile_confidence: float = 0.0
    tools_confidence: float = 0.0
    policy_confidence: float = 0.0
    model_path: str = ""

    @property
    def has_execution_tools(self) -> bool:
        return bool(self.execution_tools)


def strip_profile_hints(goal: str) -> str:
    cleaned = re.sub(
        r"Multi-source planner profile\s*\[[^\]]+\]\s*:\s*",
        "",
        goal,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"PhoneHarness\s+(?:main|safety)\s+workflow\s*\[[^\]]+\]\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return " ".join(cleaned.split())


def train_profile_model(
    examples: Iterable[PlannerProfileExample],
    *,
    strip_hints: bool = True,
) -> dict[str, Any]:
    rows = list(examples)
    if not rows:
        raise ValueError("Cannot train planner profile model without examples")

    training_rows: list[dict[str, str]] = []
    for example in rows:
        text = strip_profile_hints(example.goal) if strip_hints else example.goal
        tools_label = _encode_tools(example.execution_tools)
        training_rows.append({
            "text": text,
            "planner_profile": example.planner_profile or "unknown",
            "execution_tools": tools_label or "none",
            "policy_mode": example.policy_mode or "act",
        })

    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_type": "multinomial_naive_bayes_profile_policy",
        "strip_profile_hints": strip_hints,
        "example_count": len(training_rows),
        "execution_tool_order": EXECUTION_TOOL_ORDER,
        "models": {
            "planner_profile": _train_label_model(training_rows, "planner_profile"),
            "execution_tools": _train_label_model(training_rows, "execution_tools"),
            "policy_mode": _train_label_model(training_rows, "policy_mode"),
        },
    }


def save_profile_model(model: dict[str, Any], path: Path = DEFAULT_MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_profile_model(path: Path | None = None) -> dict[str, Any] | None:
    model_path = path or _configured_model_path()
    if os.getenv(DISABLE_ENV_VAR):
        return None
    if not model_path.exists():
        return None
    return json.loads(model_path.read_text(encoding="utf-8"))


def clear_profile_model_cache() -> None:
    _cached_model.cache_clear()


def predict_goal_profile(
    goal: str,
    *,
    model_path: Path | None = None,
) -> ProfilePrediction:
    model = load_profile_model(model_path) if model_path else _cached_model(str(_configured_model_path()))
    if not model:
        return ProfilePrediction(execution_tools=[])

    text = strip_profile_hints(goal) if model.get("strip_profile_hints", True) else goal
    profile_label, profile_confidence = _predict_label(model["models"]["planner_profile"], text)
    tools_label, tools_confidence = _predict_label(model["models"]["execution_tools"], text)
    policy_label, policy_confidence = _predict_label(model["models"]["policy_mode"], text)
    return ProfilePrediction(
        planner_profile=profile_label,
        execution_tools=_decode_tools(tools_label),
        policy_mode=policy_label if policy_label in {"act", "confirm", "refuse"} else "act",
        profile_confidence=profile_confidence,
        tools_confidence=tools_confidence,
        policy_confidence=policy_confidence,
        model_path=str(model_path or _configured_model_path()),
    )


def evaluate_profile_model(
    model: dict[str, Any],
    examples: Iterable[PlannerProfileExample],
    *,
    strip_hints: bool = True,
) -> dict[str, Any]:
    rows = list(examples)
    if not rows:
        return {
            "examples": 0,
            "planner_profile_accuracy": 0.0,
            "execution_tools_accuracy": 0.0,
            "policy_mode_accuracy": 0.0,
        }

    counts = Counter()
    mistakes: list[dict[str, Any]] = []
    for example in rows:
        text = strip_profile_hints(example.goal) if strip_hints else example.goal
        profile_label, profile_confidence = _predict_label(model["models"]["planner_profile"], text)
        tools_label, tools_confidence = _predict_label(model["models"]["execution_tools"], text)
        policy_label, policy_confidence = _predict_label(model["models"]["policy_mode"], text)
        expected_tools = _encode_tools(example.execution_tools) or "none"
        counts["examples"] += 1
        counts["planner_profile_correct"] += int(profile_label == (example.planner_profile or "unknown"))
        counts["execution_tools_correct"] += int(tools_label == expected_tools)
        counts["policy_mode_correct"] += int(policy_label == (example.policy_mode or "act"))
        if (
            profile_label != (example.planner_profile or "unknown")
            or tools_label != expected_tools
            or policy_label != (example.policy_mode or "act")
        ):
            mistakes.append({
                "goal": text[:240],
                "expected": {
                    "planner_profile": example.planner_profile,
                    "execution_tools": expected_tools,
                    "policy_mode": example.policy_mode,
                },
                "predicted": {
                    "planner_profile": profile_label,
                    "execution_tools": tools_label,
                    "policy_mode": policy_label,
                },
                "confidence": {
                    "planner_profile": round(profile_confidence, 4),
                    "execution_tools": round(tools_confidence, 4),
                    "policy_mode": round(policy_confidence, 4),
                },
            })

    total = counts["examples"]
    return {
        "examples": total,
        "planner_profile_accuracy": round(counts["planner_profile_correct"] / total, 4),
        "execution_tools_accuracy": round(counts["execution_tools_correct"] / total, 4),
        "policy_mode_accuracy": round(counts["policy_mode_correct"] / total, 4),
        "mistakes": mistakes[:20],
    }


@lru_cache(maxsize=4)
def _cached_model(path: str) -> dict[str, Any] | None:
    return load_profile_model(Path(path))


def _configured_model_path() -> Path:
    return Path(os.getenv(MODEL_ENV_VAR, str(DEFAULT_MODEL_PATH))).expanduser()


def _train_label_model(rows: list[dict[str, str]], label_key: str, balanced_prior: bool = False) -> dict[str, Any]:
    class_doc_counts: Counter[str] = Counter()
    class_token_counts: dict[str, Counter[str]] = defaultdict(Counter)
    class_total_tokens: Counter[str] = Counter()
    vocabulary: set[str] = set()

    for row in rows:
        label = row[label_key]
        tokens = _tokenize(row["text"])
        class_doc_counts[label] += 1
        class_token_counts[label].update(tokens)
        class_total_tokens[label] += len(tokens)
        vocabulary.update(tokens)

    return {
        "label_key": label_key,
        "alpha": 1.0,
        "balanced_prior": balanced_prior,
        "class_doc_counts": dict(class_doc_counts),
        "class_token_counts": {
            label: dict(counter)
            for label, counter in class_token_counts.items()
        },
        "class_total_tokens": dict(class_total_tokens),
        "vocabulary": sorted(vocabulary),
    }


def _predict_label(model: dict[str, Any], text: str) -> tuple[str, float]:
    labels = sorted(model.get("class_doc_counts", {}))
    if not labels:
        return "", 0.0

    tokens = _tokenize(text)
    token_counts = Counter(tokens)
    total_docs = sum(int(count) for count in model["class_doc_counts"].values())
    vocabulary = set(model.get("vocabulary", []))
    vocab_size = max(1, len(vocabulary))
    alpha = float(model.get("alpha", 1.0))
    scores: dict[str, float] = {}

    for label in labels:
        doc_count = int(model["class_doc_counts"][label])
        if model.get("balanced_prior", False):
            prior = math.log(1.0 / len(labels))
        else:
            prior = math.log((doc_count + alpha) / (total_docs + alpha * len(labels)))
        label_token_counts = model["class_token_counts"].get(label, {})
        total_tokens = int(model["class_total_tokens"].get(label, 0))
        denominator = total_tokens + alpha * vocab_size
        score = prior
        for token, count in token_counts.items():
            token_count = int(label_token_counts.get(token, 0))
            score += count * math.log((token_count + alpha) / denominator)
        scores[label] = score

    best_label = max(scores, key=scores.get)
    confidence = _softmax_confidence(scores, best_label)
    return best_label, confidence


def _softmax_confidence(scores: dict[str, float], best_label: str) -> float:
    best_score = scores[best_label]
    weights = [math.exp(max(-60.0, score - best_score)) for score in scores.values()]
    return float(1.0 / sum(weights))


def _tokenize(text: str) -> list[str]:
    lower = text.lower()
    chunks = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lower)
    tokens: list[str] = []
    for chunk in chunks:
        if _is_cjk_text(chunk):
            tokens.extend(chunk)
            tokens.extend(_char_ngrams(chunk, 2))
            tokens.extend(_char_ngrams(chunk, 3))
            continue
        if len(chunk) > 1:
            tokens.append(chunk)
        if len(chunk) >= 6:
            tokens.append(chunk[:4])
            tokens.append(chunk[-4:])
    return tokens or ["<empty>"]


def _is_cjk_text(token: str) -> bool:
    return all("\u4e00" <= char <= "\u9fff" for char in token)


def _char_ngrams(text: str, size: int) -> list[str]:
    if len(text) < size:
        return []
    return [text[index:index + size] for index in range(0, len(text) - size + 1)]


def _encode_tools(tools: Iterable[str]) -> str:
    seen = set(tools)
    ordered = [tool for tool in EXECUTION_TOOL_ORDER if tool in seen]
    return ",".join(ordered)


def _decode_tools(label: str) -> list[str]:
    if not label or label == "none":
        return []
    return [tool for tool in label.split(",") if tool in EXECUTION_TOOL_ORDER]
