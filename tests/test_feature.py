"""Tests for feature extraction module."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feature import (
    EMBEDDING_DIM,
    ComplexityExtractor,
    FeatureExtractor,
    ReasoningExtractor,
    SemanticExtractor,
)


def test_complexity_features():
    query = "Explain why A works.\nAlso compare B and C."
    features = ComplexityExtractor.extract(query)
    assert features["char_count"] == len(query)
    assert features["sentence_count"] >= 2
    assert features["token_count"] >= 5


def test_reasoning_keyword_count():
    query = "请解释为什么梯度下降能够收敛，并分析其与凸优化的关系。"
    result = ReasoningExtractor.extract(query)
    assert result["reasoning_keyword_count"] >= 2


def test_semantic_hash_embedding():
    SemanticExtractor.reset()
    extractor = SemanticExtractor()
    vec1 = extractor.extract("Explain why Transformer outperforms RNN.")
    vec2 = extractor.extract("Explain why Transformer outperforms RNN.")
    vec3 = extractor.extract("What is the weather today?")

    assert vec1.shape == (EMBEDDING_DIM,)
    assert np.allclose(vec1, vec2)
    assert not np.allclose(vec1, vec3)
    assert extractor.backend == "hash"


def test_feature_extractor_schema():
    SemanticExtractor.reset()
    extractor = FeatureExtractor()
    feature = extractor.extract("Explain why Transformer outperforms RNN.")

    assert len(feature.embedding) == EMBEDDING_DIM
    assert feature.token_count > 0
    assert feature.char_count > 0
    assert feature.sentence_count >= 1
    assert feature.reasoning_keyword_count >= 1

    payload = feature.to_dict()
    assert set(payload.keys()) == {
        "embedding",
        "token_count",
        "char_count",
        "sentence_count",
        "reasoning_keyword_count",
    }


def test_feature_extractor_batch():
    SemanticExtractor.reset()
    extractor = FeatureExtractor()
    queries = ["Hello world", "Prove that sqrt(2) is irrational"]
    batch = extractor.extract_batch(queries)
    assert len(batch) == 2
    assert all(len(item.embedding) == EMBEDDING_DIM for item in batch)


if __name__ == "__main__":
    test_complexity_features()
    test_reasoning_keyword_count()
    test_semantic_hash_embedding()
    test_feature_extractor_schema()
    test_feature_extractor_batch()
    print("All feature tests passed.")
