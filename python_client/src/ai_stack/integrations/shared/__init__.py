"""Shared canonical integration assets and loaders."""

from ai_stack.integrations.shared.agents import load_shared_agents
from ai_stack.integrations.shared.skills import load_shared_skills
from ai_stack.integrations.shared.tools import load_shared_tools
from ai_stack.integrations.shared.types import SharedAgentSpec, SharedSkillSpec, SharedToolSpec

__all__ = [
    "SharedAgentSpec",
    "SharedSkillSpec",
    "SharedToolSpec",
    "load_shared_agents",
    "load_shared_skills",
    "load_shared_tools",
]
