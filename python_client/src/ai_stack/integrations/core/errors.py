"""Typed errors for integration adapter layer."""

from __future__ import annotations


class IntegrationError(Exception):
    """Base integration-layer error."""


class AdapterRegistrationError(IntegrationError, ValueError):
    """Adapter registration failed due to duplicate/invalid state."""


class AdapterNotFoundError(IntegrationError, LookupError):
    """Requested adapter name was not registered."""


class AdapterValidationError(IntegrationError, RuntimeError):
    """Adapter validation failed."""


class AdapterSmokeTestError(IntegrationError, RuntimeError):
    """Adapter smoke test failed."""


__all__ = [
    "AdapterNotFoundError",
    "AdapterRegistrationError",
    "AdapterSmokeTestError",
    "AdapterValidationError",
    "IntegrationError",
]
