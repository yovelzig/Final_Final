"""Local sentence-transformer embedding adapter, satisfying `EmbeddingPort`.

`sentence-transformers` (and the `torch` it pulls in) is an optional,
heavy dependency - see the `ai_tutor` extra in `pyproject.toml`. This
module imports it lazily, inside `_load_model`, the first time
`embed_texts` actually needs it - never at module import time, so
merely importing this file (e.g. transitively, through the composition
root) never triggers a model download. Model loading and the
synchronous `model.encode(...)` call both run off the event loop via
`asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from stock_research_core.application.exceptions import EmbeddingProviderError
from stock_research_core.infrastructure.ai_tutor.config import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_NAME,
)

EMBEDDING_VERSION = "sentence-transformer-v1"


class SentenceTransformerEmbeddingAdapter:
    """Embeds text with a local `sentence-transformers` model, satisfying `EmbeddingPort`."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_EMBEDDING_MODEL_NAME,
        embedding_version: str = EMBEDDING_VERSION,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        batch_size: int = 32,
    ) -> None:
        self._model_name = model_name
        self._embedding_version = embedding_version
        self._dimension = dimension
        self._batch_size = batch_size
        self._model: Any | None = None

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
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(await asyncio.to_thread(self._encode_batch, batch))
        return vectors

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingProviderError(
                "sentence-transformers is not installed. Install it with "
                "'pip install stock-research-core[ai_tutor]' to use the local embedding provider, "
                "or set EMBEDDING_PROVIDER to a different configured provider."
            ) from exc
        try:
            self._model = SentenceTransformer(self._model_name)
        except Exception as exc:  # noqa: BLE001 - sanitize whatever the library raises
            raise EmbeddingProviderError(
                f"Failed to load embedding model '{self._model_name}'."
            ) from exc
        return self._model

    def _encode_batch(self, batch: list[str]) -> list[list[float]]:
        model = self._load_model()
        try:
            raw_vectors = model.encode(batch, normalize_embeddings=True, convert_to_numpy=True)
        except Exception as exc:  # noqa: BLE001 - sanitize whatever the library raises
            raise EmbeddingProviderError("Embedding model failed to encode the requested text.") from exc

        vectors: list[list[float]] = []
        for raw_vector in raw_vectors:
            values = [float(component) for component in raw_vector]
            if len(values) != self._dimension:
                raise EmbeddingProviderError(
                    f"Embedding model '{self._model_name}' returned a vector of dimension "
                    f"{len(values)}, expected {self._dimension} (EMBEDDING_DIMENSION)."
                )
            vectors.append(values)
        return vectors
