"""
RAG (Retrieval-Augmented Generation) subsystem for local-llm-rocm.

Components:
- embeddings: Text embedding using nomic-embed-text
- indexer: Document chunking and LanceDB storage
- retriever: Vector similarity search
- web_search: SearXNG web search integration
- server: FastAPI REST API
"""

from .config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    LANCEDB_DIR,
    DATA_DIR,
    EMBEDDING_MODEL,
    RAG_PORT,
    SEARXNG_PORT,
    SEARXNG_URL,
)

__all__ = [
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "LANCEDB_DIR",
    "DATA_DIR",
    "EMBEDDING_MODEL",
    "RAG_PORT",
    "SEARXNG_PORT",
    "SEARXNG_URL",
]
