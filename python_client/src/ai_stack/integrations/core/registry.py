"""In-memory registry for integration adapters."""

from __future__ import annotations

from typing import Dict, List

from ai_stack.integrations.core.errors import AdapterNotFoundError, AdapterRegistrationError
from ai_stack.integrations.core.protocols import IntegrationAdapter

_ADAPTERS: Dict[str, IntegrationAdapter] = {}


def register_adapter(adapter: IntegrationAdapter) -> None:
    """Register an integration adapter by unique name."""
    name = getattr(adapter, "name", "").strip()
    if not name:
        raise AdapterRegistrationError("Adapter name must be a non-empty string")

    existing = _ADAPTERS.get(name)
    if existing is not None and existing is not adapter:
        raise AdapterRegistrationError(f"Adapter already registered: {name}")

    _ADAPTERS[name] = adapter


def get_adapter(name: str) -> IntegrationAdapter:
    """Fetch adapter by name or raise AdapterNotFoundError."""
    key = (name or "").strip()
    if key in _ADAPTERS:
        return _ADAPTERS[key]
    raise AdapterNotFoundError(f"Adapter not found: {name}")


def list_adapters() -> List[str]:
    """Return sorted adapter names currently registered."""
    return sorted(_ADAPTERS.keys())


def _clear_registry_for_tests() -> None:
    """Reset adapter registry (test utility)."""
    _ADAPTERS.clear()


__all__ = ["get_adapter", "list_adapters", "register_adapter"]
