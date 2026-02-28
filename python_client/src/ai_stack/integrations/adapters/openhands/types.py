"""OpenHands adapter-specific typed payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OpenHandsRuntimeValues:
    """Canonical runtime values emitted by OpenHands adapter config."""

    provider: str
    llama_base_url: str
    api_base: str
    model: str
    workspace_root: str
    temperature: Optional[float] = None


__all__ = ["OpenHandsRuntimeValues"]
