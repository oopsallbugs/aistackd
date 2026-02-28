"""Shared canonical tools for integration sync."""

from __future__ import annotations

from typing import Dict

from ai_stack.integrations.shared.types import SharedToolSpec


DEFAULT_SHARED_TOOLS: Dict[str, SharedToolSpec] = {
    "repo-readonly-files": SharedToolSpec(
        key="repo-readonly-files",
        name="Repository Read-Only Files",
        config={
            "type": "filesystem",
            "read_only": True,
            "root_scope": "project_root",
        },
    ),
}


def load_shared_tools() -> Dict[str, SharedToolSpec]:
    """Return curated shared tool specs keyed by stable tool id."""
    return dict(DEFAULT_SHARED_TOOLS)


__all__ = ["DEFAULT_SHARED_TOOLS", "load_shared_tools"]
