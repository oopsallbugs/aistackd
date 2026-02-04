"""
Document Indexer
Discovers files, chunks them, and stores in LanceDB.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import (
    LANCEDB_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    get_collection_file_types,
    load_collections,
)
from .embeddings import embed_texts

logger = logging.getLogger(__name__)

# Initialize LanceDB connection
_lancedb_conn: lancedb.DBConnection | None = None


def get_lancedb_conn() -> lancedb.DBConnection:
    """Get or create the LanceDB connection."""
    global _lancedb_conn
    if _lancedb_conn is None:
        _lancedb_conn = lancedb.connect(str(LANCEDB_DIR))
    return _lancedb_conn


def get_or_create_table(name: str) -> lancedb.table.Table | None:
    """Get or create a LanceDB table for a collection."""
    conn = get_lancedb_conn()
    # Validate collection exists in config
    collections = load_collections()
    if name not in collections:
        raise ValueError(f"Unknown collection '{name}'. Available: {list(collections.keys())}")
    
    try:
        return conn.open_table(name)
    except Exception:
        # Table doesn't exist yet, will be created on first insert
        return None


def discover_files(paths: list[str], collection_name: str) -> list[Path]:
    """
    Discover files to index based on collection's allowed file types.
    
    Args:
        paths: List of file or directory paths
        collection_name: Name of the collection (determines allowed file types)
        
    Returns:
        List of Path objects for files to index
    """
    allowed_types = set(get_collection_file_types(collection_name))
    files: list[Path] = []
    
    for path_str in paths:
        path = Path(path_str).expanduser().resolve()
        
        if not path.exists():
            logger.warning(f"Path does not exist: {path}")
            continue
            
        if path.is_file():
            if path.suffix in allowed_types:
                files.append(path)
            else:
                logger.debug(f"Skipping file with unsupported type: {path}")
        elif path.is_dir():
            for file_path in path.rglob("*"):
                if file_path.is_file() and file_path.suffix in allowed_types:
                    # Skip hidden files and common ignore patterns
                    if not any(part.startswith(".") for part in file_path.parts):
                        if "node_modules" not in file_path.parts:
                            if "__pycache__" not in file_path.parts:
                                files.append(file_path)
    
    return files


def read_file_content(file_path: Path) -> str | None:
    """Read file content, handling encoding errors gracefully."""
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return file_path.read_text(encoding="latin-1")
        except Exception as e:
            logger.warning(f"Could not read file {file_path}: {e}")
            return None
    except Exception as e:
        logger.warning(f"Could not read file {file_path}: {e}")
        return None


def chunk_text(text: str, file_path: Path) -> list[dict[str, Any]]:
    """
    Split text into chunks with metadata.
    
    Args:
        text: The text content to chunk
        file_path: Path to the source file (for metadata)
        
    Returns:
        List of dicts with 'text' and 'metadata' keys
    """
    # Use character-based splitting with approximate token conversion
    # ~4 chars per token is a reasonable estimate
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE * 4,  # Convert tokens to chars
        chunk_overlap=CHUNK_OVERLAP * 4,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )
    
    chunks = splitter.split_text(text)
    
    return [
        {
            "text": chunk,
            "metadata": {
                "source": str(file_path),
                "filename": file_path.name,
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
        }
        for i, chunk in enumerate(chunks)
    ]


def generate_chunk_id(file_path: Path, chunk_index: int) -> str:
    """Generate a unique ID for a chunk."""
    content = f"{file_path}:{chunk_index}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def index_files(
    paths: list[str],
    collection_name: str,
) -> dict[str, Any]:
    """
    Index files into a collection.
    
    Args:
        paths: List of file or directory paths to index
        collection_name: Target collection name
        
    Returns:
        Dict with indexing statistics
    """
    conn = get_lancedb_conn()
    collections = load_collections()
    if collection_name not in collections:
        raise ValueError(f"Unknown collection '{collection_name}'")
    
    files = discover_files(paths, collection_name)
    
    if not files:
        return {
            "collection": collection_name,
            "files_found": 0,
            "chunks_indexed": 0,
            "message": "No files found matching collection file types",
        }
    
    logger.info(f"Indexing {len(files)} files to collection '{collection_name}'")
    
    all_chunks: list[dict[str, Any]] = []
    files_processed = 0
    
    for file_path in files:
        content = read_file_content(file_path)
        if content is None:
            continue
            
        if not content.strip():
            logger.debug(f"Skipping empty file: {file_path}")
            continue
            
        chunks = chunk_text(content, file_path)
        all_chunks.extend(chunks)
        files_processed += 1
    
    if not all_chunks:
        return {
            "collection": collection_name,
            "files_found": len(files),
            "files_processed": 0,
            "chunks_indexed": 0,
            "message": "No content could be extracted from files",
        }
    
    # Generate embeddings in batches
    batch_size = 32
    total_indexed = 0
    
    # Prepare data for LanceDB
    all_data = []
    
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]
        embeddings = embed_texts(texts)
        
        for j, chunk in enumerate(batch):
            chunk_id = generate_chunk_id(
                Path(chunk["metadata"]["source"]), 
                chunk["metadata"]["chunk_index"]
            )
            all_data.append({
                "id": chunk_id,
                "text": chunk["text"],
                "vector": embeddings[j],
                "source": chunk["metadata"]["source"],
                "filename": chunk["metadata"]["filename"],
                "chunk_index": chunk["metadata"]["chunk_index"],
                "total_chunks": chunk["metadata"]["total_chunks"],
            })
        
        total_indexed += len(batch)
        logger.debug(f"Processed batch {i // batch_size + 1}: {len(batch)} chunks")
    
    # Upsert to LanceDB
    try:
        table = conn.open_table(collection_name)
        # Delete existing and add new (LanceDB doesn't have native upsert)
        table.add(all_data)
    except Exception:
        # Table doesn't exist, create it
        conn.create_table(collection_name, all_data)
    
    return {
        "collection": collection_name,
        "files_found": len(files),
        "files_processed": files_processed,
        "chunks_indexed": total_indexed,
        "message": f"Successfully indexed {total_indexed} chunks from {files_processed} files",
    }


def clear_collection(collection_name: str) -> dict[str, Any]:
    """Clear all documents from a collection."""
    conn = get_lancedb_conn()
    collections = load_collections()
    
    if collection_name not in collections:
        raise ValueError(f"Unknown collection '{collection_name}'")
    
    try:
        conn.drop_table(collection_name)
        logger.info(f"Cleared collection: {collection_name}")
        return {
            "collection": collection_name,
            "message": f"Collection '{collection_name}' cleared",
        }
    except Exception as e:
        logger.warning(f"Could not clear collection {collection_name}: {e}")
        return {
            "collection": collection_name,
            "message": f"Collection '{collection_name}' was already empty or did not exist",
        }


def get_collection_stats(collection_name: str) -> dict[str, Any]:
    """Get statistics for a collection."""
    try:
        conn = get_lancedb_conn()
        collections = load_collections()
        if collection_name not in collections:
            return {
                "name": collection_name,
                "document_count": 0,
                "error": "Collection not found in config",
            }
        
        try:
            table = conn.open_table(collection_name)
            count = table.count_rows()
            return {
                "name": collection_name,
                "document_count": count,
            }
        except Exception:
            return {
                "name": collection_name,
                "document_count": 0,
            }
    except ValueError:
        return {
            "name": collection_name,
            "document_count": 0,
            "error": "Collection not found in config",
        }


def get_all_collection_stats() -> list[dict[str, Any]]:
    """Get statistics for all defined collections."""
    collections = load_collections()
    stats = []
    for name in collections:
        stat = get_collection_stats(name)
        stat["description"] = collections[name].get("description", "")
        stats.append(stat)
    return stats
