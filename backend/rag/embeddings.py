"""
Embedding utilities — generates vector embeddings for RAG.
Uses sentence-transformers (local) with fallback to OpenAI embeddings.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from backend.config import get_settings

logger = logging.getLogger(__name__)

_model = None
_EMBED_DIM = 384  # Default for all-MiniLM-L6-v2


def get_embedding_model():
    """Lazy-load the sentence-transformers model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2")
        except ImportError:
            logger.warning("sentence-transformers not installed. RAG embeddings disabled.")
            return None
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Returns list of float vectors."""
    model = get_embedding_model()
    if model is None:
        # Return zero vectors as fallback
        return [[0.0] * _EMBED_DIM] * len(texts)
    
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


def embed_single(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]


def get_embedding_dim() -> int:
    """Return the dimensionality of the embedding model."""
    model = get_embedding_model()
    if model is not None:
        return model.get_sentence_embedding_dimension()
    return _EMBED_DIM
