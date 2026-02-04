"""
Web Search via SearXNG
HTTP client for querying SearXNG metasearch engine.
"""

import logging
from typing import Any

import httpx

from .config import SEARXNG_URL

logger = logging.getLogger(__name__)

# Default timeout for web searches
SEARCH_TIMEOUT = 30.0


async def web_search(
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Search the web via SearXNG.
    
    Args:
        query: The search query
        k: Number of results to return (default 5)
        
    Returns:
        List of search results with title, url, and snippet
    """
    search_url = f"{SEARXNG_URL}/search"
    params = {
        "q": query,
        "format": "json",
        "categories": "general",
    }
    
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            response = await client.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.error(f"Web search timed out for query: {query}")
        return [{"error": "Search timed out", "query": query}]
    except httpx.HTTPStatusError as e:
        logger.error(f"Web search HTTP error: {e}")
        return [{"error": f"HTTP error: {e.response.status_code}", "query": query}]
    except httpx.ConnectError:
        logger.error(f"Could not connect to SearXNG at {SEARXNG_URL}")
        return [{"error": f"Could not connect to SearXNG at {SEARXNG_URL}", "query": query}]
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return [{"error": str(e), "query": query}]
    
    results = []
    for item in data.get("results", [])[:k]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "engine": item.get("engine", "unknown"),
        })
    
    logger.debug(f"Web search returned {len(results)} results for: {query}")
    return results


def web_search_sync(
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Synchronous version of web search.
    
    Args:
        query: The search query
        k: Number of results to return (default 5)
        
    Returns:
        List of search results with title, url, and snippet
    """
    search_url = f"{SEARXNG_URL}/search"
    params = {
        "q": query,
        "format": "json",
        "categories": "general",
    }
    
    try:
        with httpx.Client(timeout=SEARCH_TIMEOUT) as client:
            response = client.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.error(f"Web search timed out for query: {query}")
        return [{"error": "Search timed out", "query": query}]
    except httpx.HTTPStatusError as e:
        logger.error(f"Web search HTTP error: {e}")
        return [{"error": f"HTTP error: {e.response.status_code}", "query": query}]
    except httpx.ConnectError:
        logger.error(f"Could not connect to SearXNG at {SEARXNG_URL}")
        return [{"error": f"Could not connect to SearXNG at {SEARXNG_URL}", "query": query}]
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return [{"error": str(e), "query": query}]
    
    results = []
    for item in data.get("results", [])[:k]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "engine": item.get("engine", "unknown"),
        })
    
    logger.debug(f"Web search returned {len(results)} results for: {query}")
    return results


async def check_searxng_health() -> dict[str, Any]:
    """Check if SearXNG is available."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{SEARXNG_URL}/healthz")
            if response.status_code == 200:
                return {"status": "healthy", "url": SEARXNG_URL}
            # Some SearXNG instances don't have /healthz, try the main page
            response = await client.get(SEARXNG_URL)
            if response.status_code == 200:
                return {"status": "healthy", "url": SEARXNG_URL}
            return {"status": "unhealthy", "url": SEARXNG_URL, "code": response.status_code}
    except Exception as e:
        return {"status": "unavailable", "url": SEARXNG_URL, "error": str(e)}
