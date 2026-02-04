"""
Embedding Model Wrapper
Uses sentence-transformers with nomic-embed-text model.
Runs on CPU to leave GPU free for llama.cpp.
"""

import logging
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from .config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the embedding model (cached singleton)."""
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
    # Force CPU to leave GPU for llama.cpp
    # trust_remote_code needed for nomic models
    model = SentenceTransformer(
        EMBEDDING_MODEL,
        device="cpu",
        trust_remote_code=True,
    )
    logger.info(f"Embedding model loaded: {model.get_sentence_embedding_dimension()} dimensions")
    return model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts into vectors.
    
    Args:
        texts: List of text strings to embed
        
    Returns:
        List of embedding vectors (each is a list of floats)
    """
    if not texts:
        return []
    
    model = get_model()
    # nomic-embed-text requires a task prefix for documents
    # Using "search_document: " for indexing, "search_query: " for queries
    prefixed = [f"search_document: {t}" for t in texts]
    embeddings = model.encode(prefixed, convert_to_numpy=True, show_progress_bar=False)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """
    Embed a single query for retrieval.
    Uses "search_query: " prefix for nomic-embed-text.
    
    Args:
        query: The search query
        
    Returns:
        Embedding vector as list of floats
    """
    model = get_model()
    prefixed = f"search_query: {query}"
    embedding = model.encode(prefixed, convert_to_numpy=True, show_progress_bar=False)
    return embedding.tolist()


def get_embedding_dimension() -> int:
    """Get the dimensionality of embeddings."""
    model = get_model()
    return model.get_sentence_embedding_dimension()
