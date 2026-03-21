"""Tests for EmbeddingService.

All tests mock SentenceTransformer to avoid downloading the 1.2GB
gte-large-en-v1.5 model during test runs. The mock produces numpy
arrays of the correct shape (1024 dimensions) with normalized values.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_model(dimension: int = 1024) -> MagicMock:
    """Build a mock SentenceTransformer that returns correct-shape arrays."""
    mock = MagicMock()
    mock.get_sentence_embedding_dimension.return_value = dimension

    def _encode(text_or_texts, normalize_embeddings: bool = False, batch_size: int = 32):
        if isinstance(text_or_texts, str):
            vec = np.random.randn(dimension).astype(np.float32)
        else:
            vec = np.random.randn(len(text_or_texts), dimension).astype(np.float32)
        if normalize_embeddings:
            if vec.ndim == 1:
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
            else:
                norms = np.linalg.norm(vec, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                vec = vec / norms
        return vec

    mock.encode.side_effect = _encode
    mock.to.return_value = mock
    mock.device = MagicMock(type="cpu")
    return mock


@pytest.fixture
def mock_sentence_transformer():
    """Patch SentenceTransformer so it returns a mock model."""
    mock_model = _make_mock_model()
    with patch(
        "osint_system.data_management.embeddings.SentenceTransformer",
        return_value=mock_model,
    ) as patched:
        yield patched, mock_model


@pytest.fixture
def embedding_service(mock_sentence_transformer):
    """Create an EmbeddingService with mocked model."""
    from osint_system.data_management.embeddings import EmbeddingService

    # Force CPU device to avoid CUDA requirement in CI.
    return EmbeddingService(device="cpu")


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------

class TestConstruction:
    """Verify EmbeddingService initialization behavior."""

    def test_constructs_with_defaults(self, mock_sentence_transformer):
        """Service constructs with default model name and auto device."""
        from osint_system.data_management.embeddings import EmbeddingService

        with patch(
            "osint_system.data_management.embeddings.torch"
        ) as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            svc = EmbeddingService()

        _, mock_model = mock_sentence_transformer
        mock_model.to.assert_called_with("cpu")

    def test_constructs_with_explicit_device(self, mock_sentence_transformer):
        """Explicit device parameter is forwarded to model.to()."""
        from osint_system.data_management.embeddings import EmbeddingService

        svc = EmbeddingService(device="cpu")
        _, mock_model = mock_sentence_transformer
        mock_model.to.assert_called_with("cpu")

    def test_dimension_property(self, embedding_service):
        """Dimension property returns model's embedding dimension."""
        assert embedding_service.dimension == 1024

    def test_raises_on_none_dimension(self, mock_sentence_transformer):
        """Raises RuntimeError if model reports no dimension."""
        from osint_system.data_management.embeddings import EmbeddingService

        _, mock_model = mock_sentence_transformer
        mock_model.get_sentence_embedding_dimension.return_value = None

        with pytest.raises(RuntimeError, match="did not report an embedding dimension"):
            EmbeddingService(device="cpu")


# ---------------------------------------------------------------------------
# Async embed tests
# ---------------------------------------------------------------------------

class TestEmbed:
    """Verify single-text async embedding."""

    @pytest.mark.asyncio
    async def test_returns_list_of_floats(self, embedding_service):
        """embed() returns a Python list of float values."""
        result = await embedding_service.embed("Test sentence for embedding.")
        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_returns_normalized_vector(self, embedding_service):
        """Returned vector has unit L2 norm (normalized)."""
        result = await embedding_service.embed("Normalize this vector.")
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"

    @pytest.mark.asyncio
    async def test_empty_string_returns_zero_vector(self, embedding_service):
        """Empty string produces a zero vector, not an error."""
        result = await embedding_service.embed("")
        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(v == 0.0 for v in result)

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_zero_vector(self, embedding_service):
        """Whitespace-only input treated as empty."""
        result = await embedding_service.embed("   \t\n  ")
        assert len(result) == 1024
        assert all(v == 0.0 for v in result)


# ---------------------------------------------------------------------------
# Async embed_batch tests
# ---------------------------------------------------------------------------

class TestEmbedBatch:
    """Verify batch embedding."""

    @pytest.mark.asyncio
    async def test_returns_correct_count(self, embedding_service):
        """embed_batch() returns one vector per input text."""
        texts = ["First sentence.", "Second sentence.", "Third one."]
        results = await embedding_service.embed_batch(texts)
        assert len(results) == 3
        assert all(len(v) == 1024 for v in results)

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self, embedding_service):
        """Empty input list returns empty output list."""
        results = await embedding_service.embed_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_single_item_batch(self, embedding_service):
        """Single-item batch works correctly."""
        results = await embedding_service.embed_batch(["Solo text."])
        assert len(results) == 1
        assert len(results[0]) == 1024

    @pytest.mark.asyncio
    async def test_custom_batch_size(self, embedding_service):
        """Custom batch_size parameter is forwarded to encode()."""
        texts = ["a", "b"]
        await embedding_service.embed_batch(texts, batch_size=1)
        # Verify batch_size was passed to encode
        call_kwargs = embedding_service._model.encode.call_args
        assert call_kwargs[1]["batch_size"] == 1


# ---------------------------------------------------------------------------
# Sync embed tests
# ---------------------------------------------------------------------------

class TestEmbedSync:
    """Verify synchronous embedding interface."""

    def test_returns_list_of_floats(self, embedding_service):
        """embed_sync() returns a list of 1024 floats."""
        result = embedding_service.embed_sync("Synchronous embedding test.")
        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(v, float) for v in result)

    def test_empty_string_returns_zero_vector(self, embedding_service):
        """Empty string produces zero vector in sync mode."""
        result = embedding_service.embed_sync("")
        assert len(result) == 1024
        assert all(v == 0.0 for v in result)

    def test_normalized(self, embedding_service):
        """Sync embedding is also normalized."""
        result = embedding_service.embed_sync("Check normalization.")
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-5
