"""Host runtime service configuration and validation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from aistackd.runtime.backends import backend_installation_errors
from aistackd.state.host import HostRuntimeState, HostStateStore

DEFAULT_HOST_BIND = "127.0.0.1"
DEFAULT_HOST_PORT = 8000
DEFAULT_HOST_API_KEY_ENV = "AISTACKD_API_KEY"
DEFAULT_BACKEND_BIND = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8011
DEFAULT_BACKEND_CONTEXT_SIZE = 24576
DEFAULT_BACKEND_PREDICT_LIMIT = 4096
DEFAULT_BACKEND_PARALLEL = 1
DEFAULT_BACKEND_BATCH_SIZE: int | None = None
DEFAULT_BACKEND_UBATCH_SIZE: int | None = None
DEFAULT_BACKEND_GPU_LAYERS: int | None = None
DEFAULT_BACKEND_FIT_TARGET: int | None = None
DEFAULT_BACKEND_NO_KV_OFFLOAD: bool | None = None
DEFAULT_BACKEND_NO_OP_OFFLOAD: bool | None = None
DEFAULT_BACKEND_CACHE_RAM: int | None = None

_ENVIRONMENT_VARIABLE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_BIND_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


@dataclass(frozen=True)
class HostServiceConfig:
    """Minimal service config for the local control plane."""

    bind_host: str = DEFAULT_HOST_BIND
    port: int = DEFAULT_HOST_PORT
    api_key_env: str = DEFAULT_HOST_API_KEY_ENV
    backend_bind_host: str = DEFAULT_BACKEND_BIND
    backend_port: int = DEFAULT_BACKEND_PORT
    backend_context_size: int = DEFAULT_BACKEND_CONTEXT_SIZE
    backend_predict_limit: int = DEFAULT_BACKEND_PREDICT_LIMIT
    backend_parallel: int = DEFAULT_BACKEND_PARALLEL
    backend_batch_size: int | None = DEFAULT_BACKEND_BATCH_SIZE
    backend_ubatch_size: int | None = DEFAULT_BACKEND_UBATCH_SIZE
    backend_gpu_layers: int | None = DEFAULT_BACKEND_GPU_LAYERS
    backend_fit_target: int | None = DEFAULT_BACKEND_FIT_TARGET
    backend_no_kv_offload: bool | None = DEFAULT_BACKEND_NO_KV_OFFLOAD
    backend_no_op_offload: bool | None = DEFAULT_BACKEND_NO_OP_OFFLOAD
    backend_cache_ram: int | None = DEFAULT_BACKEND_CACHE_RAM

    def normalized(self) -> "HostServiceConfig":
        """Return a copy with whitespace normalized."""
        return HostServiceConfig(
            bind_host=self.bind_host.strip(),
            port=self.port,
            api_key_env=self.api_key_env.strip(),
            backend_bind_host=self.backend_bind_host.strip(),
            backend_port=self.backend_port,
            backend_context_size=self.backend_context_size,
            backend_predict_limit=self.backend_predict_limit,
            backend_parallel=self.backend_parallel,
            backend_batch_size=self.backend_batch_size,
            backend_ubatch_size=self.backend_ubatch_size,
            backend_gpu_layers=self.backend_gpu_layers,
            backend_fit_target=self.backend_fit_target,
            backend_no_kv_offload=self.backend_no_kv_offload,
            backend_no_op_offload=self.backend_no_op_offload,
            backend_cache_ram=self.backend_cache_ram,
        )

    @property
    def base_url(self) -> str:
        """Return the northbound base URL for the control plane."""
        normalized = self.normalized()
        return f"http://{normalized.bind_host}:{normalized.port}"

    @property
    def responses_base_url(self) -> str:
        """Return the Open Responses-compatible base path."""
        return f"{self.base_url}/v1"

    @property
    def backend_base_url(self) -> str:
        """Return the internal backend URL used by the control plane."""
        normalized = self.normalized()
        return f"http://{normalized.backend_bind_host}:{normalized.backend_port}"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "bind_host": self.bind_host,
            "port": self.port,
            "api_key_env": self.api_key_env,
            "backend_bind_host": self.backend_bind_host,
            "backend_port": self.backend_port,
            "backend_context_size": self.backend_context_size,
            "backend_predict_limit": self.backend_predict_limit,
            "backend_parallel": self.backend_parallel,
            "base_url": self.base_url,
            "responses_base_url": self.responses_base_url,
            "backend_base_url": self.backend_base_url,
        }
        if self.backend_batch_size is not None:
            payload["backend_batch_size"] = self.backend_batch_size
        if self.backend_ubatch_size is not None:
            payload["backend_ubatch_size"] = self.backend_ubatch_size
        if self.backend_gpu_layers is not None:
            payload["backend_gpu_layers"] = self.backend_gpu_layers
        if self.backend_fit_target is not None:
            payload["backend_fit_target"] = self.backend_fit_target
        if self.backend_no_kv_offload is not None:
            payload["backend_no_kv_offload"] = self.backend_no_kv_offload
        if self.backend_no_op_offload is not None:
            payload["backend_no_op_offload"] = self.backend_no_op_offload
        if self.backend_cache_ram is not None:
            payload["backend_cache_ram"] = self.backend_cache_ram
        return payload


@dataclass(frozen=True)
class HostValidationResult:
    """Result of validating host runtime readiness."""

    ok: bool
    errors: tuple[str, ...]
    service: HostServiceConfig
    runtime: HostRuntimeState

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "service": self.service.to_dict(),
            "runtime": self.runtime.to_dict(),
        }


def validate_host_runtime(
    store: HostStateStore,
    service: HostServiceConfig,
) -> HostValidationResult:
    """Validate that host state and service config are runnable."""
    runtime = store.load_runtime_state()
    normalized_service = service.normalized()
    errors: list[str] = []

    if not normalized_service.bind_host:
        errors.append("bind_host is required")
    elif " " in normalized_service.bind_host or not _BIND_HOST_RE.fullmatch(normalized_service.bind_host):
        errors.append("bind_host must be a non-empty hostname or IPv4 address")

    if not isinstance(normalized_service.port, int) or not (1 <= normalized_service.port <= 65535):
        errors.append("port must be an integer between 1 and 65535")

    if not normalized_service.backend_bind_host:
        errors.append("backend_bind_host is required")
    elif " " in normalized_service.backend_bind_host or not _BIND_HOST_RE.fullmatch(normalized_service.backend_bind_host):
        errors.append("backend_bind_host must be a non-empty hostname or IPv4 address")

    if not isinstance(normalized_service.backend_port, int) or not (1 <= normalized_service.backend_port <= 65535):
        errors.append("backend_port must be an integer between 1 and 65535")
    if not isinstance(normalized_service.backend_context_size, int) or normalized_service.backend_context_size < 1:
        errors.append("backend_context_size must be a positive integer")
    if not isinstance(normalized_service.backend_predict_limit, int) or normalized_service.backend_predict_limit < 1:
        errors.append("backend_predict_limit must be a positive integer")
    if not isinstance(normalized_service.backend_parallel, int) or normalized_service.backend_parallel < 1:
        errors.append("backend_parallel must be a positive integer")
    if (
        normalized_service.backend_batch_size is not None
        and (
            not isinstance(normalized_service.backend_batch_size, int)
            or normalized_service.backend_batch_size < 1
        )
    ):
        errors.append("backend_batch_size must be a positive integer")
    if (
        normalized_service.backend_ubatch_size is not None
        and (
            not isinstance(normalized_service.backend_ubatch_size, int)
            or normalized_service.backend_ubatch_size < 1
        )
    ):
        errors.append("backend_ubatch_size must be a positive integer")
    if (
        normalized_service.backend_gpu_layers is not None
        and (
            not isinstance(normalized_service.backend_gpu_layers, int)
            or normalized_service.backend_gpu_layers < -1
        )
    ):
        errors.append("backend_gpu_layers must be an integer greater than or equal to -1")
    if (
        normalized_service.backend_fit_target is not None
        and (
            not isinstance(normalized_service.backend_fit_target, int)
            or normalized_service.backend_fit_target < 0
        )
    ):
        errors.append("backend_fit_target must be a non-negative integer")
    if (
        normalized_service.backend_no_kv_offload is not None
        and not isinstance(normalized_service.backend_no_kv_offload, bool)
    ):
        errors.append("backend_no_kv_offload must be a boolean")
    if (
        normalized_service.backend_no_op_offload is not None
        and not isinstance(normalized_service.backend_no_op_offload, bool)
    ):
        errors.append("backend_no_op_offload must be a boolean")
    if (
        normalized_service.backend_cache_ram is not None
        and (
            not isinstance(normalized_service.backend_cache_ram, int)
            or normalized_service.backend_cache_ram < -1
        )
    ):
        errors.append("backend_cache_ram must be an integer greater than or equal to -1")

    if (
        normalized_service.bind_host == normalized_service.backend_bind_host
        and normalized_service.port == normalized_service.backend_port
    ):
        errors.append("backend_port must not match the control-plane port on the same bind host")

    if not _ENVIRONMENT_VARIABLE_RE.fullmatch(normalized_service.api_key_env):
        errors.append("api_key_env must be a valid uppercase environment variable name")
    elif not os.getenv(normalized_service.api_key_env, "").strip():
        errors.append(f"api key environment variable '{normalized_service.api_key_env}' is not set or empty")

    if not runtime.installed_models:
        errors.append("no installed models are available for host runtime")

    errors.extend(backend_installation_errors(runtime.backend_installation))

    if runtime.active_model is None:
        errors.append("no active model is configured for host runtime")
    elif runtime.activation_state != "ready":
        errors.append(
            f"active model '{runtime.active_model}' is not ready for serving "
            f"(activation_state={runtime.activation_state})"
        )

    return HostValidationResult(
        ok=not errors,
        errors=tuple(errors),
        service=normalized_service,
        runtime=runtime,
    )


def validate_backend_runtime(
    store: HostStateStore,
    service: HostServiceConfig,
) -> HostValidationResult:
    """Validate only the backend-launch prerequisites for the managed host runtime."""
    runtime = store.load_runtime_state()
    normalized_service = service.normalized()
    errors: list[str] = []

    if not normalized_service.backend_bind_host:
        errors.append("backend_bind_host is required")
    elif " " in normalized_service.backend_bind_host or not _BIND_HOST_RE.fullmatch(normalized_service.backend_bind_host):
        errors.append("backend_bind_host must be a non-empty hostname or IPv4 address")

    if not isinstance(normalized_service.backend_port, int) or not (1 <= normalized_service.backend_port <= 65535):
        errors.append("backend_port must be an integer between 1 and 65535")
    if not isinstance(normalized_service.backend_context_size, int) or normalized_service.backend_context_size < 1:
        errors.append("backend_context_size must be a positive integer")
    if not isinstance(normalized_service.backend_predict_limit, int) or normalized_service.backend_predict_limit < 1:
        errors.append("backend_predict_limit must be a positive integer")
    if not isinstance(normalized_service.backend_parallel, int) or normalized_service.backend_parallel < 1:
        errors.append("backend_parallel must be a positive integer")
    if (
        normalized_service.backend_batch_size is not None
        and (
            not isinstance(normalized_service.backend_batch_size, int)
            or normalized_service.backend_batch_size < 1
        )
    ):
        errors.append("backend_batch_size must be a positive integer")
    if (
        normalized_service.backend_ubatch_size is not None
        and (
            not isinstance(normalized_service.backend_ubatch_size, int)
            or normalized_service.backend_ubatch_size < 1
        )
    ):
        errors.append("backend_ubatch_size must be a positive integer")
    if (
        normalized_service.backend_gpu_layers is not None
        and (
            not isinstance(normalized_service.backend_gpu_layers, int)
            or normalized_service.backend_gpu_layers < -1
        )
    ):
        errors.append("backend_gpu_layers must be an integer greater than or equal to -1")
    if (
        normalized_service.backend_fit_target is not None
        and (
            not isinstance(normalized_service.backend_fit_target, int)
            or normalized_service.backend_fit_target < 0
        )
    ):
        errors.append("backend_fit_target must be a non-negative integer")
    if (
        normalized_service.backend_no_kv_offload is not None
        and not isinstance(normalized_service.backend_no_kv_offload, bool)
    ):
        errors.append("backend_no_kv_offload must be a boolean")
    if (
        normalized_service.backend_no_op_offload is not None
        and not isinstance(normalized_service.backend_no_op_offload, bool)
    ):
        errors.append("backend_no_op_offload must be a boolean")
    if (
        normalized_service.backend_cache_ram is not None
        and (
            not isinstance(normalized_service.backend_cache_ram, int)
            or normalized_service.backend_cache_ram < -1
        )
    ):
        errors.append("backend_cache_ram must be an integer greater than or equal to -1")

    if (
        normalized_service.bind_host == normalized_service.backend_bind_host
        and normalized_service.port == normalized_service.backend_port
    ):
        errors.append("backend_port must not match the control-plane port on the same bind host")

    if not runtime.installed_models:
        errors.append("no installed models are available for host runtime")

    errors.extend(backend_installation_errors(runtime.backend_installation))

    if runtime.active_model is None:
        errors.append("no active model is configured for host runtime")
    elif runtime.activation_state != "ready":
        errors.append(
            f"active model '{runtime.active_model}' is not ready for serving "
            f"(activation_state={runtime.activation_state})"
        )

    return HostValidationResult(
        ok=not errors,
        errors=tuple(errors),
        service=normalized_service,
        runtime=runtime,
    )


def resolve_api_key(service: HostServiceConfig) -> str:
    """Resolve the API key for a validated service config."""
    normalized_service = service.normalized()
    api_key = os.getenv(normalized_service.api_key_env, "").strip()
    if not api_key:
        raise ValueError(f"api key environment variable '{normalized_service.api_key_env}' is not set or empty")
    return api_key
