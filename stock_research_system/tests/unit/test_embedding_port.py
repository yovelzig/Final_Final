"""Unit tests for `EmbeddingPort` conformance via the deterministic
test-only fake adapter. No real model is loaded anywhere in this file.
"""

from __future__ import annotations

import math

import pytest

from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DETERMINISTIC_FAKE_EMBEDDING_DIMENSION,
    DeterministicFakeEmbeddingAdapter,
)


class TestDeterministicFakeEmbeddingAdapter:
    async def test_same_text_produces_identical_vector(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter()
        [first] = await adapter.embed_texts(["diversification reduces risk"])
        [second] = await adapter.embed_texts(["diversification reduces risk"])
        assert first == second

    async def test_different_text_produces_different_vector(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter()
        [first] = await adapter.embed_texts(["diversification"])
        [second] = await adapter.embed_texts(["concentration"])
        assert first != second

    async def test_case_and_whitespace_insensitive(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter()
        [first] = await adapter.embed_texts(["Diversification Reduces Risk"])
        [second] = await adapter.embed_texts(["  diversification reduces risk  "])
        assert first == second

    async def test_dimension_matches_configured_value(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter(dimension=64)
        [vector] = await adapter.embed_texts(["text"])
        assert len(vector) == 64 == adapter.dimension

    async def test_default_dimension_matches_production_column(self) -> None:
        assert DETERMINISTIC_FAKE_EMBEDDING_DIMENSION == 384
        assert DeterministicFakeEmbeddingAdapter().dimension == 384

    async def test_vectors_are_unit_normalized(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter()
        [vector] = await adapter.embed_texts(["some text to embed"])
        magnitude = math.sqrt(sum(component * component for component in vector))
        assert magnitude == pytest.approx(1.0, abs=1e-9)

    async def test_empty_input_returns_empty_list(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter()
        assert await adapter.embed_texts([]) == []

    async def test_batch_matches_individual_calls(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter()
        batch = await adapter.embed_texts(["alpha", "beta"])
        individual = [(await adapter.embed_texts(["alpha"]))[0], (await adapter.embed_texts(["beta"]))[0]]
        assert batch == individual

    def test_exposes_model_name_and_version(self) -> None:
        adapter = DeterministicFakeEmbeddingAdapter()
        assert adapter.model_name
        assert adapter.embedding_version
