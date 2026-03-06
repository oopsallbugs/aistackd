"""Shared helpers for scaffold command handlers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def render_placeholder(
    *,
    command_name: str,
    phase: str,
    summary: str,
    details: Sequence[str] = (),
    project_root: Path | None = None,
) -> int:
    """Print a consistent scaffold placeholder message."""
    root = (project_root or Path.cwd()).resolve()

    print(f"{command_name}: scaffold command")
    print(f"phase: {phase}")
    print(f"project_root: {root}")
    print(f"summary: {summary}")
    for detail in details:
        print(detail)

    return 0
