"""Shared canonical agents for integration sync."""

from __future__ import annotations

from typing import Dict

from ai_stack.integrations.shared.types import SharedAgentSpec


DEFAULT_SHARED_AGENTS: Dict[str, SharedAgentSpec] = {
    "general-code-assistant": SharedAgentSpec(
        key="general-code-assistant",
        name="General Code Assistant",
        config={
            "mode": "balanced",
            "read_only": False,
        },
    ),
}


def load_shared_agents() -> Dict[str, SharedAgentSpec]:
    """Return curated shared agent specs keyed by stable agent id."""
    return dict(DEFAULT_SHARED_AGENTS)


__all__ = ["DEFAULT_SHARED_AGENTS", "load_shared_agents"]
