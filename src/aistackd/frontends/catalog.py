"""Supported frontend targets for the scaffold."""

from __future__ import annotations

from collections.abc import Sequence

SUPPORTED_FRONTENDS = ("codex", "opencode")


def normalize_frontend_targets(targets: Sequence[str] | None) -> tuple[str, ...]:
    """Normalize sync target selection, defaulting to all supported frontends."""
    if not targets:
        return SUPPORTED_FRONTENDS

    seen: list[str] = []
    for target in targets:
        if target not in seen:
            seen.append(target)
    return tuple(seen)
