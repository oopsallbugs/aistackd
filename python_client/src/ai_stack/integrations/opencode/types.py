"""OpenCode adapter-specific typed payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class OpenCodeModelLimit:
    """Token limits for an OpenCode model entry."""

    context: int
    output: int


@dataclass(frozen=True)
class OpenCodeModelEntry:
    """Single model entry under a provider in OpenCode config."""

    name: str
    tools: bool
    limit: OpenCodeModelLimit


@dataclass(frozen=True)
class OpenCodeProviderOptions:
    """Provider options for OpenCode."""

    baseURL: str


@dataclass(frozen=True)
class OpenCodeProvider:
    """OpenCode provider config payload."""

    npm: str
    name: str
    options: OpenCodeProviderOptions
    models: Dict[str, OpenCodeModelEntry]


@dataclass(frozen=True)
class OpenCodeRuntimeValues:
    """Canonical runtime values emitted by OpenCode adapter config."""

    provider: str
    provider_key: str
    provider_config: OpenCodeProvider
    base_url: str
    model: str
    api_format: str = "openai-compatible"
    temperature: Optional[float] = None


__all__ = [
    "OpenCodeModelEntry",
    "OpenCodeModelLimit",
    "OpenCodeProvider",
    "OpenCodeProviderOptions",
    "OpenCodeRuntimeValues",
]
