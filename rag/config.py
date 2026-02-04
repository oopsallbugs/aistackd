"""
RAG Configuration
Paths, ports, and collection definitions.
"""

import os
from pathlib import Path
from typing import Any

import yaml

# Paths
RAG_DIR = Path(__file__).parent
PROJECT_ROOT = RAG_DIR.parent
DATA_DIR = RAG_DIR / "data"
LANCEDB_DIR = DATA_DIR / "lancedb"
COLLECTIONS_FILE = RAG_DIR / "collections.yml"

# Ensure data directories exist
DATA_DIR.mkdir(exist_ok=True)
LANCEDB_DIR.mkdir(exist_ok=True)

# Server ports
RAG_PORT = int(os.environ.get("RAG_PORT", "8081"))
SEARXNG_PORT = int(os.environ.get("SEARXNG_PORT", "8888"))
SEARXNG_URL = os.environ.get("SEARXNG_URL", f"http://127.0.0.1:{SEARXNG_PORT}")

# Embedding model
EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")

# Chunking settings (Level 2 RAG best practices)
CHUNK_SIZE = int(os.environ.get("RAG_CHUNK_SIZE", "400"))  # tokens
CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "100"))  # tokens


def load_collections() -> dict[str, Any]:
    """Load collection definitions from collections.yml."""
    if not COLLECTIONS_FILE.exists():
        return {
            "coding": {
                "description": "Code and technical documentation",
                "file_types": [".py", ".js", ".ts", ".sh", ".md", ".txt"],
            },
            "notes": {
                "description": "General notes and documents",
                "file_types": [".md", ".txt"],
            },
        }

    with open(COLLECTIONS_FILE) as f:
        data = yaml.safe_load(f)

    return data.get("collections", {})


def get_collection_file_types(collection_name: str) -> list[str]:
    """Get allowed file types for a collection."""
    collections = load_collections()
    if collection_name not in collections:
        raise ValueError(f"Unknown collection: {collection_name}")
    return collections[collection_name].get("file_types", [])


def list_collections() -> list[dict[str, Any]]:
    """List all defined collections with their descriptions."""
    collections = load_collections()
    return [
        {
            "name": name,
            "description": config.get("description", ""),
            "file_types": config.get("file_types", []),
        }
        for name, config in collections.items()
    ]
