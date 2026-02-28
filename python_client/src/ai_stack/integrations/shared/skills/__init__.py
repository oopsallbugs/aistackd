"""Shared canonical skills for integration sync."""

from __future__ import annotations

from typing import Dict

from ai_stack.integrations.shared.types import SharedSkillSpec


DEFAULT_SHARED_SKILLS: Dict[str, SharedSkillSpec] = {
    "ask-clarifying-questions": SharedSkillSpec(
        key="ask-clarifying-questions",
        name="Ask Clarifying Questions",
        description="Gather missing requirements before proposing implementation steps.",
        content=(
            "Ask concise clarification questions when requirements are ambiguous, then summarize "
            "the agreed scope before implementation."
        ),
    ),
}


def load_shared_skills() -> Dict[str, SharedSkillSpec]:
    """Return curated shared skill specs keyed by stable skill id."""
    return dict(DEFAULT_SHARED_SKILLS)


__all__ = ["DEFAULT_SHARED_SKILLS", "load_shared_skills"]
