"""Runtime-layer exports."""

from aistackd.runtime.config import CURRENT_RUNTIME_CONFIG_SCHEMA_VERSION, RuntimeConfig
from aistackd.runtime.backends import (
    LLAMA_CLI_BINARY_NAME,
    LLAMA_SERVER_BINARY_NAME,
    BackendDiscoveryResult,
    adopt_backend_installation,
    backend_installation_errors,
    discover_llama_cpp_installation,
)
from aistackd.runtime.host import (
    DEFAULT_HOST_API_KEY_ENV,
    DEFAULT_HOST_BIND,
    DEFAULT_HOST_PORT,
    HostServiceConfig,
    HostValidationResult,
    resolve_api_key,
    validate_host_runtime,
)
from aistackd.runtime.modes import RuntimeMode, all_runtime_modes
from aistackd.runtime.prereqs import HostInspectionReport, HostPrerequisiteCheck, inspect_host_environment

__all__ = [
    "CURRENT_RUNTIME_CONFIG_SCHEMA_VERSION",
    "DEFAULT_HOST_API_KEY_ENV",
    "DEFAULT_HOST_BIND",
    "DEFAULT_HOST_PORT",
    "BackendDiscoveryResult",
    "HostServiceConfig",
    "HostInspectionReport",
    "HostPrerequisiteCheck",
    "HostValidationResult",
    "LLAMA_CLI_BINARY_NAME",
    "LLAMA_SERVER_BINARY_NAME",
    "RuntimeConfig",
    "RuntimeMode",
    "adopt_backend_installation",
    "all_runtime_modes",
    "backend_installation_errors",
    "discover_llama_cpp_installation",
    "inspect_host_environment",
    "resolve_api_key",
    "validate_host_runtime",
]
