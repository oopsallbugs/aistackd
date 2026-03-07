"""Model selection contracts shared across profiles and frontends."""

from __future__ import annotations

import re

SINGLE_ACTIVE_MODEL_POLICY = "profile_scoped_single_active_model"

_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_MODEL_KEY_SANITIZE_RE = re.compile(r"[^a-z0-9]+")


def normalize_model_name(model_name: str) -> str:
    """Normalize a configured model name."""
    return model_name.strip()


def validate_model_name(model_name: str) -> tuple[str, ...]:
    """Return definition errors for a configured model name."""
    normalized = normalize_model_name(model_name)
    messages: list[str] = []

    if not normalized:
        messages.append("model is required")
    elif any(character.isspace() for character in normalized):
        messages.append("model must not contain whitespace")
    elif _CONTROL_CHARACTER_RE.search(normalized):
        messages.append("model must not contain control characters")

    return tuple(messages)


def frontend_model_key(model_name: str) -> str:
    """Return a frontend-safe key derived from a model name."""
    normalized = normalize_model_name(model_name).lower()
    key = _MODEL_KEY_SANITIZE_RE.sub("-", normalized).strip("-")
    return key or "model"
