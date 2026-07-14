from __future__ import annotations

import hashlib
import os
from typing import ClassVar

import numpy as np

EMBEDDING_DIM = 384
BGE_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def _hash_embed(query: str, dim: int = EMBEDDING_DIM) -> np.ndarray:
    """Deterministic local embedding — no model download or API required."""
    vec = np.zeros(dim, dtype=np.float32)
    for i in range(dim):
        digest = hashlib.sha256(f"{query}:{i}".encode("utf-8")).digest()
        val = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF * 2.0 - 1.0
        vec[i] = val
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


class SemanticExtractor:
    """
    Convert a natural language query into a 384-d semantic embedding.

    Modes (EMBEDDING_MODE env):
    - hash  : local deterministic fallback (default, no download)
    - bge   : BAAI/bge-small-en-v1.5 via sentence-transformers
    - auto  : try bge, fall back to hash on failure
    """

    _instance: ClassVar["SemanticExtractor | None"] = None
    _model: ClassVar[object | None] = None
    _backend: ClassVar[str | None] = None

    def __new__(cls) -> "SemanticExtractor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — useful in tests."""
        cls._instance = None
        cls._model = None
        cls._backend = None

    @property
    def backend(self) -> str:
        self._ensure_loaded()
        assert self._backend is not None
        return self._backend

    def _resolve_mode(self) -> str:
        return os.getenv("EMBEDDING_MODE", "hash").lower()

    def _load_bge(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(BGE_MODEL_NAME)
        self._backend = "bge"

    def _ensure_loaded(self) -> None:
        if self._backend is not None:
            return

        mode = self._resolve_mode()
        if mode == "hash":
            self._backend = "hash"
            return

        if mode in ("bge", "auto"):
            try:
                self._load_bge()
                return
            except Exception as exc:
                if mode == "bge":
                    raise RuntimeError(
                        f"Failed to load {BGE_MODEL_NAME}. "
                        "Install sentence-transformers or set EMBEDDING_MODE=hash."
                    ) from exc
                self._backend = "hash"
                return

        raise ValueError(f"Unknown EMBEDDING_MODE: {mode}. Use hash, bge, or auto.")

    def extract(self, query: str) -> np.ndarray:
        self._ensure_loaded()
        if self._backend == "hash":
            return _hash_embed(query)
        assert self._model is not None
        vector = self._model.encode(query, normalize_embeddings=True)
        return np.asarray(vector, dtype=np.float32)

    def extract_batch(self, queries: list[str]) -> np.ndarray:
        """Batch inference — shape (n, 384)."""
        self._ensure_loaded()
        if self._backend == "hash":
            return np.stack([_hash_embed(q) for q in queries])
        assert self._model is not None
        vectors = self._model.encode(queries, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)
