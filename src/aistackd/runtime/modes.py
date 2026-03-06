"""Runtime modes for the v1 scaffold."""

from __future__ import annotations

from enum import StrEnum


class RuntimeMode(StrEnum):
    """Documented runtime modes for aistackd."""

    HOST = "host"
    CLIENT = "client"
    HYBRID = "hybrid"


def all_runtime_modes() -> tuple[str, ...]:
    """Return the runtime mode values in a stable order."""
    return tuple(mode.value for mode in RuntimeMode)
