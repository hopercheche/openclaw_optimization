from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.feature.complexity import ComplexityExtractor
from src.feature.reasoning import ReasoningExtractor
from src.feature.semantic import EMBEDDING_DIM, SemanticExtractor


@dataclass
class FeatureVector:
    embedding: list[float]
    token_count: int
    char_count: int
    sentence_count: int
    reasoning_keyword_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "embedding": self.embedding,
            "token_count": self.token_count,
            "char_count": self.char_count,
            "sentence_count": self.sentence_count,
            "reasoning_keyword_count": self.reasoning_keyword_count,
        }


class FeatureExtractor:
    """
    Unified feature extraction interface.

    Input Query → Feature Extractor → Feature Vector
    """

    def __init__(self, semantic: SemanticExtractor | None = None) -> None:
        self._semantic = semantic or SemanticExtractor()

    @property
    def embedding_backend(self) -> str:
        return self._semantic.backend

    def extract(self, query: str) -> FeatureVector:
        embedding = self._semantic.extract(query)
        complexity = ComplexityExtractor.extract(query)
        reasoning = ReasoningExtractor.extract(query)
        return FeatureVector(
            embedding=embedding.tolist(),
            token_count=complexity["token_count"],
            char_count=complexity["char_count"],
            sentence_count=complexity["sentence_count"],
            reasoning_keyword_count=reasoning["reasoning_keyword_count"],
            metadata={"embedding_dim": EMBEDDING_DIM, "backend": self.embedding_backend},
        )

    def extract_dict(self, query: str) -> dict[str, Any]:
        return self.extract(query).to_dict()

    def extract_batch(self, queries: list[str]) -> list[FeatureVector]:
        embeddings = self._semantic.extract_batch(queries)
        results: list[FeatureVector] = []
        for query, embedding in zip(queries, embeddings):
            complexity = ComplexityExtractor.extract(query)
            reasoning = ReasoningExtractor.extract(query)
            results.append(
                FeatureVector(
                    embedding=np.asarray(embedding, dtype=np.float32).tolist(),
                    token_count=complexity["token_count"],
                    char_count=complexity["char_count"],
                    sentence_count=complexity["sentence_count"],
                    reasoning_keyword_count=reasoning["reasoning_keyword_count"],
                    metadata={"embedding_dim": EMBEDDING_DIM, "backend": self.embedding_backend},
                )
            )
        return results
