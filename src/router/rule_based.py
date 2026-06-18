from __future__ import annotations

import re

from src.config import load_config
from src.router.base import BaseRouter
from src.types import ModelTier, RoutingDecision


class RuleBasedRouter(BaseRouter):
    """
    MVP Rule-based Router.

    Routes queries to small / mid / large model tiers using:
    - Reasoning keyword detection (why, compare, explain, ...)
    - Input length thresholds
    - Simple complexity heuristics (sentence count, question marks, code blocks)
    """

    def __init__(self) -> None:
        cfg = load_config()["router"]
        self._keywords = [k.lower() for k in cfg["reasoning_keywords"]]
        self._length = cfg["length_thresholds"]
        self._complexity = cfg["complexity_thresholds"]
        self._weights = cfg["weights"]

    def _keyword_score(self, query: str) -> tuple[float, list[str]]:
        lower = query.lower()
        hits = [kw for kw in self._keywords if kw in lower]
        if not hits:
            return 0.0, ["无推理关键词 → 倾向 small"]
        score = min(1.0, len(hits) * 0.25 + (0.15 if any(k in hits for k in ("prove", "derive", "证明", "推导")) else 0))
        return score, [f"检测到推理关键词: {', '.join(hits[:5])}"]

    def _length_score(self, query: str) -> tuple[float, list[str]]:
        n = len(query)
        if n <= self._length["short"]:
            return 0.0, [f"输入较短 ({n} chars) → 倾向 small"]
        if n <= self._length["medium"]:
            return 0.5, [f"输入中等 ({n} chars) → 倾向 mid"]
        return 1.0, [f"输入较长 ({n} chars) → 倾向 large"]

    def _complexity_score(self, query: str) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0

        sentences = re.split(r"[.!?。！？\n]+", query)
        sentence_count = len([s for s in sentences if s.strip()])
        if sentence_count >= 3:
            score += 0.3
            reasons.append(f"多句结构 ({sentence_count} 句)")

        question_marks = query.count("?") + query.count("？")
        if question_marks >= 2:
            score += 0.2
            reasons.append(f"多个问题 ({question_marks} 个问号)")

        if re.search(r"```|`[^`]+`", query):
            score += 0.3
            reasons.append("包含代码块")

        if re.search(r"\d+\s*[+\-*/=]\s*\d+|[∫∑∏√]", query):
            score += 0.2
            reasons.append("包含数学/公式信号")

        word_count = len(query.split())
        if word_count > 80:
            score += 0.2
            reasons.append(f"词汇量较大 ({word_count} words)")

        score = min(1.0, score)
        if not reasons:
            reasons.append("结构简单 → 倾向 small")
        return score, reasons

    def _score_to_tier(self, combined: float) -> ModelTier:
        if combined < 0.35:
            return ModelTier.SMALL
        if combined < 0.65:
            return ModelTier.MID
        return ModelTier.LARGE

    def route(self, query: str) -> RoutingDecision:
        kw_score, kw_reasons = self._keyword_score(query)
        len_score, len_reasons = self._length_score(query)
        cx_score, cx_reasons = self._complexity_score(query)

        w = self._weights
        combined = (
            w["keyword"] * kw_score
            + w["length"] * len_score
            + w["complexity"] * cx_score
        )

        tier = self._score_to_tier(combined)
        confidence = abs(combined - 0.35) if tier == ModelTier.SMALL else (
            abs(combined - 0.5) if tier == ModelTier.MID else abs(combined - 0.65)
        )
        confidence = min(1.0, 0.5 + confidence)

        reasons = kw_reasons + len_reasons + cx_reasons
        reasons.append(f"综合得分 {combined:.2f} → 路由至 {tier.value} 模型")

        return RoutingDecision(
            tier=tier,
            confidence=round(confidence, 3),
            reasons=reasons,
            scores={
                "keyword": round(kw_score, 3),
                "length": round(len_score, 3),
                "complexity": round(cx_score, 3),
                "combined": round(combined, 3),
            },
        )
