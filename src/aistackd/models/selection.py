"""Model selection contracts shared across profiles, acquisition, and frontends."""

from __future__ import annotations

import re

SINGLE_ACTIVE_MODEL_POLICY = "profile_scoped_single_active_model"

_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_MODEL_KEY_SANITIZE_RE = re.compile(r"[^a-z0-9]+")
_MODEL_NAME_SANITIZE_RE = re.compile(r"[^a-z0-9.-]+")
_QUANTIZATION_RE = re.compile(r"(q\d+(?:_[a-z0-9]+)+)", flags=re.IGNORECASE)


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


def derive_model_name_from_artifact_name(filename: str) -> str:
    """Derive a stable model identifier from a GGUF filename or stem."""
    stem = re.sub(r"\.gguf$", "", filename.strip(), flags=re.IGNORECASE).lower()
    normalized = stem.replace("_", "-")
    normalized = _MODEL_NAME_SANITIZE_RE.sub("-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-.")
    return normalized or "model"


def infer_quantization_from_artifact_name(filename: str) -> str:
    """Infer GGUF quantization from a filename when possible."""
    match = _QUANTIZATION_RE.search(filename.replace("-", "_"))
    if match is not None:
        return match.group(1).lower()
    for token in re.split(r"[._-]+", filename.upper()):
        if token.startswith("Q") and any(character.isdigit() for character in token):
            return token.lower()
    return "unknown"
