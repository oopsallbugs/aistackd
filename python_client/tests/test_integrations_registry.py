from __future__ import annotations

import pytest

from ai_stack.integrations.core import (
    AdapterNotFoundError,
    AdapterRegistrationError,
    IntegrationRuntimeConfig,
    IntegrationSmokeResult,
    IntegrationValidationResult,
    get_adapter,
    list_adapters,
    register_adapter,
)
from ai_stack.integrations.core.registry import _clear_registry_for_tests


class _Adapter:
    def __init__(self, name: str):
        self.name = name

    def validate(self, context):
        _ = context
        return IntegrationValidationResult(ok=True, messages=[])

    def build_runtime_config(self, context):
        _ = context
        return IntegrationRuntimeConfig(name=self.name, values={})

    def smoke_test(self, context):
        _ = context
        return IntegrationSmokeResult(ok=True, details="ok")


@pytest.fixture(autouse=True)
def _reset_registry():
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


def test_registry_register_get_and_list() -> None:
    alpha = _Adapter("alpha")
    beta = _Adapter("beta")

    register_adapter(beta)
    register_adapter(alpha)

    assert get_adapter("alpha") is alpha
    assert get_adapter("beta") is beta
    assert list_adapters() == ["alpha", "beta"]


def test_registry_rejects_duplicate_name_from_different_instance() -> None:
    register_adapter(_Adapter("alpha"))

    with pytest.raises(AdapterRegistrationError):
        register_adapter(_Adapter("alpha"))


def test_registry_allows_re_registering_same_instance() -> None:
    adapter = _Adapter("alpha")

    register_adapter(adapter)
    register_adapter(adapter)

    assert list_adapters() == ["alpha"]


def test_registry_missing_adapter_raises_lookup_error() -> None:
    with pytest.raises(AdapterNotFoundError):
        get_adapter("missing")


def test_registry_rejects_empty_name() -> None:
    with pytest.raises(AdapterRegistrationError):
        register_adapter(_Adapter(""))
