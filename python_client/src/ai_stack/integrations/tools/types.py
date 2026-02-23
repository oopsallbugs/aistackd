"""Types for tool adapter interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ReadToolResult:
    """Result for read-only file fetch."""

    ok: bool
    path: str
    content: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class DirectoryListingResult:
    """Result for read-only directory listing."""

    ok: bool
    path: str
    files: List[str]
    error: Optional[str] = None


__all__ = ["DirectoryListingResult", "ReadToolResult"]
