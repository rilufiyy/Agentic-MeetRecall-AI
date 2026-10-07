"""
Embedding service - wraps sentence-transformers for dense text representations.

Model: paraphrase-multilingual-MiniLM-L12-v2
  - Supports 50+ languages (English, Indonesian, etc.)
  - 384-dimensional embeddings
  - ~117 MB download
  - Normalized embeddings -> cosine similarity = dot product

To switch to a higher-quality (but heavier) model, change EMBEDDING_MODEL_ID to:
  "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"  (768-dim, ~420 MB)
"""
from __future__ import annotations

import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384          

class EmbeddingService:
    """Singleton wrapper around SentenceTransformer model."""

    _model = None

    def _load(self) -> None:
        if EmbeddingService._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_ID}")
        EmbeddingService._model = SentenceTransformer(EMBEDDING_MODEL_ID)
        logger.info("Embedding model loaded.")

    def encode(self, texts: List[str]) -> np.ndarray:
        """Encode a list of strings -> (N, 384) float32 array (L2-normalised)."""
        self._load()
        return EmbeddingService._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=64,
        ).astype(np.float32)

    def encode_single(self, text: str) -> np.ndarray:
        """Encode one string -> (384,) float32 array."""
        return self.encode([text])[0]

embedding_service = EmbeddingService()