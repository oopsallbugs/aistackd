"""Shared CLI-facing error rendering helpers."""

from __future__ import annotations

from typing import Optional


def print_error(message: str, detail: Optional[str] = None) -> None:
    """Print a user-facing error in a consistent format."""
    print(f"❌ Error: {message}")
    if detail:
        print(f"   {detail}")


def exit_with_error(message: str, detail: Optional[str] = None, exit_code: int = 1) -> None:
    """Print an error and exit with a non-zero status code."""
    print_error(message=message, detail=detail)
    raise SystemExit(exit_code)
