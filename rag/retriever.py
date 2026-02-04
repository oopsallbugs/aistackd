"""
Vector Retriever
Query LanceDB collections for similar documents.
"""

import logging
from typing import Any

from .embeddings import embed_query
from .indexer import get_lancedb_conn, load_collections

logger = logging.getLogger(__name__)


def search(
    collection_name: str,
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Search a collection for documents similar to the query.
    
    Args:
        collection_name: Name of the collection to search
        query: The search query
        k: Number of results to return (default 5)
        
    Returns:
        List of results with text, metadata, and similarity score
    """
    collections = load_collections()
    if collection_name not in collections:
        raise ValueError(f"Unknown collection '{collection_name}'. Available: {list(collections.keys())}")
    
    conn = get_lancedb_conn()
    
    try:
        table = conn.open_table(collection_name)
    except Exception:
        logger.info(f"Collection '{collection_name}' is empty or doesn't exist")
        return []
    
    if table.count_rows() == 0:
        logger.info(f"Collection '{collection_name}' is empty")
        return []
    
    # Embed the query
    query_embedding = embed_query(query)
    
    # Query LanceDB
    results = (
        table.search(query_embedding)
        .limit(k)
        .to_pandas()
    )
    
    # Format results
    formatted = []
    for _, row in results.iterrows():
        # LanceDB returns _distance (L2 distance by default)
        distance = row.get("_distance", 0.0)
        # Convert distance to similarity score
        # Lower distance = higher similarity
        similarity = 1.0 / (1.0 + distance)
        
        formatted.append({
            "text": row["text"],
            "metadata": {
                "source": row.get("source", "unknown"),
                "filename": row.get("filename", "unknown"),
                "chunk_index": row.get("chunk_index", 0),
                "total_chunks": row.get("total_chunks", 1),
            },
            "similarity": round(similarity, 4),
            "source": row.get("source", "unknown"),
            "filename": row.get("filename", "unknown"),
        })
    
    logger.debug(f"Found {len(formatted)} results for query in '{collection_name}'")
    return formatted


def search_all_collections(
    query: str,
    k: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """
    Search all collections for documents similar to the query.
    
    Args:
        query: The search query
        k: Number of results per collection
        
    Returns:
        Dict mapping collection names to their results
    """
    collections = load_collections()
    results = {}
    
    for collection_name in collections:
        try:
            collection_results = search(collection_name, query, k)
            if collection_results:
                results[collection_name] = collection_results
        except Exception as e:
            logger.warning(f"Error searching collection '{collection_name}': {e}")
    
    return results
