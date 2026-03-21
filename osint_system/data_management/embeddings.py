"""Local embedding generation service wrapping sentence-transformers.

Provides async and sync interfaces for generating 1024-dimension normalized
vectors using gte-large-en-v1.5. Designed for pgvector column population
on facts, articles, entities, and reports.

GPU (CUDA) is used when available, falling back to CPU. The model is loaded
once at construction time -- not per call -- to amortize the ~2s load cost.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Wraps SentenceTransformer for async/sync embedding generation.

    The model (gte-large-en-v1.5 by default) produces 1024-dimension
    normalized vectors suitable for cosine similarity via pgvector.

    Args:
        model_name: HuggingFace model identifier. Default is
            Alibaba-NLP/gte-large-en-v1.5 (1024 dims, 1.2GB).
        device: Target device ("cuda", "cpu", or None for auto-detect).
            When None, selects CUDA if available, otherwise CPU.
    """

    def __init__(
        self,
        model_name: str = "Alibaba-NLP/gte-large-en-v1.5",
        device: Optional[str] = None,
    ) -> None:
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        self._device = device
        self._model_name = model_name
        self._model = SentenceTransformer(model_name, trust_remote_code=True)
        self._model.to(device)

        # Cache the output dimension from the model's configuration.
        # SentenceTransformer exposes this via get_sentence_embedding_dimension().
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError(
                f"Model {model_name!r} did not report an embedding dimension. "
                "Cannot validate output vectors."
            )
        self._dimension: int = int(dim)

        logger.info(
            "EmbeddingService initialized: model=%s, device=%s, dimension=%d",
            model_name,
            device,
            self._dimension,
        )

    @property
    def dimension(self) -> int:
        """Output embedding dimension (1024 for gte-large-en-v1.5)."""
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string asynchronously.

        Runs the encode call in a thread executor so the CPU/GPU-bound
        work does not block the event loop.

        Args:
            text: Input text to embed.

        Returns:
            Normalized vector as a list of floats with length == self.dimension.
            Empty string produces a zero vector.
        """
        if not text or not text.strip():
            return [0.0] * self._dimension

        text = text[:30000]  # Truncate to stay within model's token limit

        loop = asyncio.get_running_loop()
        try:
            vector: np.ndarray = await loop.run_in_executor(
                None,
                lambda: self._model.encode(text, normalize_embeddings=True),
            )
            return vector.tolist()
        except RuntimeError as e:
            logger.warning("Embedding failed (returning zero vector): %s", e)
            return [0.0] * self._dimension

    async def embed_batch(
        self, texts: list[str], batch_size: int = 32
    ) -> list[list[float]]:
        """Embed multiple texts in a single batched call.

        Args:
            texts: List of input texts.
            batch_size: Batch size for GPU throughput tuning.

        Returns:
            List of normalized vectors, one per input text.
            Empty input list returns empty output list.
        """
        if not texts:
            return []

        loop = asyncio.get_running_loop()
        vectors: np.ndarray = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                texts, normalize_embeddings=True, batch_size=batch_size
            ),
        )
        return vectors.tolist()

    def embed_sync(self, text: str) -> list[float]:
        """Synchronous embedding for migration scripts and non-async contexts.

        Args:
            text: Input text to embed.

        Returns:
            Normalized vector as a list of floats.
            Empty string produces a zero vector.
        """
        if not text or not text.strip():
            return [0.0] * self._dimension

        # Truncate to avoid CUDA index-out-of-bounds on very long inputs.
        # gte-large-en-v1.5 max sequence length is 8192 tokens (~32K chars).
        text = text[:30000]

        try:
            vector: np.ndarray = self._model.encode(
                text, normalize_embeddings=True
            )
            return vector.tolist()
        except RuntimeError as e:
            # CUDA assertion failures on malformed input — return zero vector
            logger.warning("Embedding failed (returning zero vector): %s", e)
            return [0.0] * self._dimension
