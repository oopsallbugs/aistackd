"""Shared canonical agents for integration sync."""

from __future__ import annotations

from typing import Dict

from ai_stack.integrations.shared.types import SharedAgentSpec


# Populate this map with curated shared agent specs.
DEFAULT_SHARED_AGENTS: Dict[str, SharedAgentSpec] = {}


def load_shared_agents() -> Dict[str, SharedAgentSpec]:
    """Return curated shared agent specs keyed by stable agent id."""
    return dict(DEFAULT_SHARED_AGENTS)


__all__ = ["DEFAULT_SHARED_AGENTS", "load_shared_agents"]
