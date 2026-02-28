"""Canonical shared integration asset types (frontend-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class SharedToolSpec:
    """Shared tool spec that frontend adapters map to runtime config shapes."""

    key: str
    name: str
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SharedAgentSpec:
    """Shared agent spec that frontend adapters map to runtime config shapes."""

    key: str
    name: str
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SharedSkillSpec:
    """Shared skill spec that frontend adapters map to target skill formats."""

    key: str
    name: str
    description: str
    content: str
    config: Dict[str, Any] = field(default_factory=dict)


__all__ = ["SharedAgentSpec", "SharedSkillSpec", "SharedToolSpec"]
