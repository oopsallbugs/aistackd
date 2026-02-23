"""Integration core contracts and registry."""

from ai_stack.integrations.core.errors import (
    AdapterNotFoundError,
    AdapterRegistrationError,
    AdapterSmokeTestError,
    AdapterValidationError,
    IntegrationError,
)
from ai_stack.integrations.core.protocols import IntegrationAdapter
from ai_stack.integrations.core.registry import get_adapter, list_adapters, register_adapter
from ai_stack.integrations.core.types import (
    IntegrationContext,
    IntegrationRuntimeConfig,
    IntegrationSmokeResult,
    IntegrationValidationResult,
)

__all__ = [
    "AdapterNotFoundError",
    "AdapterRegistrationError",
    "AdapterSmokeTestError",
    "AdapterValidationError",
    "IntegrationAdapter",
    "IntegrationContext",
    "IntegrationError",
    "IntegrationRuntimeConfig",
    "IntegrationSmokeResult",
    "IntegrationValidationResult",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]
