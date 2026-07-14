from __future__ import annotations

from src.feature.keywords import REASONING_KEYWORDS


class ReasoningExtractor:
    """Extract reasoning signal features from query text."""

    KEYWORDS = REASONING_KEYWORDS

    @classmethod
    def _is_chinese_keyword(cls, keyword: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in keyword)

    @classmethod
    def count_keywords(cls, query: str) -> int:
        lower = query.lower()
        matched: set[str] = set()
        for keyword in cls.KEYWORDS:
            if cls._is_chinese_keyword(keyword):
                if keyword in query:
                    matched.add(keyword)
            elif keyword.lower() in lower:
                matched.add(keyword)
        return len(matched)

    @classmethod
    def extract(cls, query: str) -> dict[str, int]:
        return {"reasoning_keyword_count": cls.count_keywords(query)}
