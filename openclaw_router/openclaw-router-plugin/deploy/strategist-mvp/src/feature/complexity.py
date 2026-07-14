from __future__ import annotations

import re


class ComplexityExtractor:
    """Extract complexity features: token_count, char_count, sentence_count."""

    @staticmethod
    def _estimate_token_count(text: str) -> int:
        """Local token estimate without API (English words + CJK chars)."""
        english_tokens = len(re.findall(r"\b\w+\b", text))
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        punctuation_tokens = len(re.findall(r"[^\w\s]", text))
        return max(1, english_tokens + cjk_chars + punctuation_tokens // 2)

    @staticmethod
    def _count_sentences(text: str) -> int:
        parts = re.split(r"[.!?。！？\n]+", text)
        return max(1, len([p for p in parts if p.strip()]))

    @classmethod
    def extract(cls, query: str) -> dict[str, int]:
        return {
            "token_count": cls._estimate_token_count(query),
            "char_count": len(query),
            "sentence_count": cls._count_sentences(query),
        }
