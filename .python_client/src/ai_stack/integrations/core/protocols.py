"""Protocols for integration adapter implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ai_stack.integrations.core.types import (
    IntegrationContext,
    IntegrationRuntimeConfig,
    IntegrationSmokeResult,
    IntegrationValidationResult,
)


@runtime_checkable
class IntegrationAdapter(Protocol):
    """Common lifecycle contract for integration adapters."""

    name: str

    def validate(self, context: IntegrationContext) -> IntegrationValidationResult: ...

    def build_runtime_config(self, context: IntegrationContext) -> IntegrationRuntimeConfig: ...

    def smoke_test(self, context: IntegrationContext) -> IntegrationSmokeResult: ...


__all__ = ["IntegrationAdapter"]
