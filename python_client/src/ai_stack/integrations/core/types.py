"""Shared typed contracts for integration adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class IntegrationContext:
    """Runtime context passed into integration adapters."""

    project_root: Path
    llama_api_url: str
    default_model: Optional[str]
    create_client: Callable[..., Any]


@dataclass(frozen=True)
class IntegrationValidationResult:
    """Validation result for an integration adapter."""

    ok: bool
    messages: List[str]


@dataclass(frozen=True)
class IntegrationRuntimeConfig:
    """Adapter-specific runtime configuration payload."""

    name: str
    values: Dict[str, Any]


@dataclass(frozen=True)
class IntegrationSmokeResult:
    """Result of adapter smoke test probe."""

    ok: bool
    details: str


__all__ = [
    "IntegrationContext",
    "IntegrationRuntimeConfig",
    "IntegrationSmokeResult",
    "IntegrationValidationResult",
]
