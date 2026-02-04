"""
RAG FastAPI Server
Exposes indexing, search, and web search endpoints.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import RAG_PORT, list_collections
from .indexer import (
    clear_collection,
    get_all_collection_stats,
    index_files,
)
from .retriever import search, search_all_collections
from .web_search import check_searxng_health, web_search

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"RAG server starting on port {RAG_PORT}")
    # Pre-load the embedding model on startup
    try:
        from .embeddings import get_model
        get_model()
        logger.info("Embedding model loaded successfully")
    except Exception as e:
        logger.warning(f"Could not pre-load embedding model: {e}")
    yield
    logger.info("RAG server shutting down")


app = FastAPI(
    title="RAG Server",
    description="Document indexing, retrieval, and web search for local-llm-rocm",
    version="1.0.0",
    lifespan=lifespan,
)


# Request/Response models
class IndexRequest(BaseModel):
    """Request to index files into a collection."""
    collection: str = Field(..., description="Target collection name")
    paths: list[str] = Field(..., description="File or directory paths to index")


class SearchRequest(BaseModel):
    """Request to search a collection."""
    collection: str = Field(..., description="Collection to search")
    query: str = Field(..., description="Search query")
    k: int = Field(default=5, ge=1, le=20, description="Number of results")


class WebSearchRequest(BaseModel):
    """Request to perform a web search."""
    query: str = Field(..., description="Search query")
    k: int = Field(default=5, ge=1, le=20, description="Number of results")


class SearchResult(BaseModel):
    """A single search result."""
    text: str
    source: str
    filename: str
    similarity: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSearchResult(BaseModel):
    """A single web search result."""
    title: str
    url: str
    snippet: str
    engine: str = "unknown"


# Endpoints
@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    searxng_status = await check_searxng_health()
    return {
        "status": "healthy",
        "service": "rag-server",
        "searxng": searxng_status,
    }


@app.get("/collections")
async def get_collections() -> list[dict[str, Any]]:
    """List all collections with their stats."""
    stats = get_all_collection_stats()
    return stats


@app.delete("/collections/{name}")
async def delete_collection(name: str) -> dict[str, Any]:
    """Clear all documents from a collection."""
    try:
        result = clear_collection(name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/index")
async def index_documents(request: IndexRequest) -> dict[str, Any]:
    """Index files or directories into a collection."""
    try:
        result = index_files(request.paths, request.collection)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error indexing documents")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search")
async def search_documents(request: SearchRequest) -> list[dict[str, Any]]:
    """Search a collection for similar documents."""
    try:
        results = search(request.collection, request.query, request.k)
        return results
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error searching documents")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/all")
async def search_all(request: WebSearchRequest) -> dict[str, list[dict[str, Any]]]:
    """Search all collections for similar documents."""
    try:
        results = search_all_collections(request.query, request.k)
        return results
    except Exception as e:
        logger.exception("Error searching all collections")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/web")
async def web_search_endpoint(request: WebSearchRequest) -> list[dict[str, Any]]:
    """Perform a web search via SearXNG."""
    try:
        results = await web_search(request.query, request.k)
        return results
    except Exception as e:
        logger.exception("Error performing web search")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Run the server directly."""
    import uvicorn
    uvicorn.run(
        "rag.server:app",
        host="127.0.0.1",
        port=RAG_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
