"""TEST-ONLY / DEVELOPMENT-ONLY deterministic embedding adapter.

Do not use this in production - it produces stable, hash-derived
vectors from text, not a real semantic embedding. It exists so unit and
integration tests (including tests that exercise the real pgvector
column and HNSW index) never need to download or run an actual model,
per the Phase 8 spec ss4: "Tests must use a deterministic test-only
embedding implementation ... do not make tests download a model."

The default dimension (384) matches the production
`knowledge_chunk_embeddings.embedding` column so it can be used
directly in integration tests without a schema mismatch.
"""

from __future__ import annotations

import hashlib
import math

DETERMINISTIC_FAKE_EMBEDDING_MODEL_NAME = "test-only-deterministic-fake-embedding"
DETERMINISTIC_FAKE_EMBEDDING_VERSION = "fake-v1"
DETERMINISTIC_FAKE_EMBEDDING_DIMENSION = 384


class DeterministicFakeEmbeddingAdapter:
    """TEST-ONLY. Deterministic, hash-derived, unit-normalized vectors. Satisfies `EmbeddingPort`."""

    def __init__(
        self,
        *,
        dimension: int = DETERMINISTIC_FAKE_EMBEDDING_DIMENSION,
        model_name: str = DETERMINISTIC_FAKE_EMBEDDING_MODEL_NAME,
        embedding_version: str = DETERMINISTIC_FAKE_EMBEDDING_VERSION,
    ) -> None:
        self._dimension = dimension
        self._model_name = model_name
        self._embedding_version = embedding_version

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def embedding_version(self) -> str:
        return self._embedding_version

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        normalized = text.strip().lower()
        raw_values = [
            self._hash_component(normalized, index) for index in range(self._dimension)
        ]
        magnitude = math.sqrt(sum(value * value for value in raw_values)) or 1.0
        return [value / magnitude for value in raw_values]

    @staticmethod
    def _hash_component(text: str, index: int) -> float:
        digest = hashlib.sha256(f"{text}::{index}".encode("utf-8")).digest()
        # Map the first 8 digest bytes to a signed float in [-1, 1], deterministically.
        as_int = int.from_bytes(digest[:8], byteorder="big", signed=False)
        return (as_int / (2**64 - 1)) * 2.0 - 1.0
