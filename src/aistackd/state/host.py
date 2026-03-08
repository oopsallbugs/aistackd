"""Host-side model inventory, backend adoption, process state, and activation state."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from aistackd.models.selection import frontend_model_key
from aistackd.models.sources import (
    BACKEND_ACQUISITION_POLICY,
    MODEL_SOURCE_POLICY,
    PRIMARY_BACKEND,
    SourceModel,
    SUPPORTED_MODEL_SOURCES,
)
from aistackd.state.files import load_json_object, write_json_atomic
from aistackd.state.profiles import RUNTIME_STATE_DIRECTORY_NAME

HOST_DIRECTORY_NAME = "host"
HOST_RUNTIME_FILE_NAME = "runtime.json"
INSTALLED_MODELS_FILE_NAME = "installed_models.json"
MODEL_RECEIPTS_DIRECTORY_NAME = "model_receipts"
BACKEND_INSTALLATION_FILE_NAME = "backend_installation.json"
BACKEND_PROCESS_FILE_NAME = "backend_process.json"
CONTROL_PLANE_PROCESS_FILE_NAME = "control_plane_process.json"
MANAGED_BACKENDS_DIRECTORY_NAME = "backends"
MANAGED_MODELS_DIRECTORY_NAME = "models"
HOST_LOGS_DIRECTORY_NAME = "logs"
RESPONSES_STATE_DIRECTORY_NAME = "responses"
DEFAULT_RESPONSE_STATE_RETENTION_LIMIT = 128
CURRENT_HOST_STATE_SCHEMA_VERSION = "v1alpha1"


class HostStateError(RuntimeError):
    """Base exception for host-state operations."""


class InstalledModelNotFoundError(HostStateError):
    """Raised when a requested installed model does not exist."""


@dataclass(frozen=True)
class StoredResponseState:
    """Persisted conversation state for one Responses follow-up chain."""

    response_id: str
    model_name: str
    messages: tuple[dict[str, object], ...]
    updated_at: str

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "StoredResponseState":
        response_id = _require_string(payload, "response_id")
        model_name = _require_string(payload, "model_name")
        updated_at = _require_string(payload, "updated_at")
        messages_value = payload.get("messages")
        if not isinstance(messages_value, list) or not all(isinstance(entry, dict) for entry in messages_value):
            raise HostStateError("expected 'messages' to be a list of objects")
        return cls(
            response_id=response_id,
            model_name=model_name,
            messages=tuple(deepcopy(entry) for entry in messages_value),
            updated_at=updated_at,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "response_id": self.response_id,
            "model_name": self.model_name,
            "messages": [deepcopy(entry) for entry in self.messages],
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class HostStatePaths:
    """Canonical host-state paths."""

    runtime_state_root: Path
    host_dir: Path
    runtime_state_path: Path
    installed_models_path: Path
    model_receipts_dir: Path
    backend_installation_path: Path
    backend_process_path: Path
    control_plane_process_path: Path
    managed_backends_dir: Path
    managed_models_dir: Path
    host_logs_dir: Path
    responses_state_dir: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> "HostStatePaths":
        """Derive host-state paths from the project root."""
        root = project_root.resolve()
        runtime_state_root = root / RUNTIME_STATE_DIRECTORY_NAME
        host_dir = runtime_state_root / HOST_DIRECTORY_NAME
        return cls(
            runtime_state_root=runtime_state_root,
            host_dir=host_dir,
            runtime_state_path=host_dir / HOST_RUNTIME_FILE_NAME,
            installed_models_path=host_dir / INSTALLED_MODELS_FILE_NAME,
            model_receipts_dir=host_dir / MODEL_RECEIPTS_DIRECTORY_NAME,
            backend_installation_path=host_dir / BACKEND_INSTALLATION_FILE_NAME,
            backend_process_path=host_dir / BACKEND_PROCESS_FILE_NAME,
            control_plane_process_path=host_dir / CONTROL_PLANE_PROCESS_FILE_NAME,
            managed_backends_dir=host_dir / MANAGED_BACKENDS_DIRECTORY_NAME,
            managed_models_dir=host_dir / MANAGED_MODELS_DIRECTORY_NAME,
            host_logs_dir=host_dir / HOST_LOGS_DIRECTORY_NAME,
            responses_state_dir=host_dir / RESPONSES_STATE_DIRECTORY_NAME,
        )

    def receipt_path(self, model_name: str) -> Path:
        """Return the receipt path for one installed model."""
        return self.model_receipts_dir / f"{frontend_model_key(model_name)}.json"

    def backend_workspace_dir(self, backend_name: str = PRIMARY_BACKEND) -> Path:
        """Return the managed workspace root for one backend."""
        return self.managed_backends_dir / backend_name

    def backend_install_dir(self, backend_name: str = PRIMARY_BACKEND) -> Path:
        """Return the managed install root for one backend."""
        return self.backend_workspace_dir(backend_name) / "install"

    def backend_extract_dir(self, backend_name: str = PRIMARY_BACKEND) -> Path:
        """Return the managed extraction root for one backend."""
        return self.backend_workspace_dir(backend_name) / "extract"

    def backend_source_dir(self, backend_name: str = PRIMARY_BACKEND) -> Path:
        """Return the managed source-copy root for one backend."""
        return self.backend_workspace_dir(backend_name) / "source"

    def backend_build_dir(self, backend_name: str = PRIMARY_BACKEND) -> Path:
        """Return the managed build root for one backend."""
        return self.backend_workspace_dir(backend_name) / "build"

    def model_workspace_dir(self, model_name: str) -> Path:
        """Return the managed workspace root for one installed model."""
        return self.managed_models_dir / frontend_model_key(model_name)

    def model_artifact_dir(self, model_name: str) -> Path:
        """Return the managed artifact directory for one installed model."""
        return self.model_workspace_dir(model_name) / "artifact"

    def backend_log_path(self, backend_name: str = PRIMARY_BACKEND) -> Path:
        """Return the persisted backend log path for one backend."""
        return self.host_logs_dir / f"{frontend_model_key(backend_name)}.log"

    def control_plane_log_path(self) -> Path:
        """Return the persisted control-plane log path."""
        return self.host_logs_dir / "control-plane.log"

    def response_state_path(self, response_id: str) -> Path:
        """Return the persisted response-state path for one response id."""
        return self.responses_state_dir / f"{response_id}.json"


@dataclass(frozen=True)
class HostBackendInstallation:
    """Persisted adopted backend installation record."""

    backend: str
    acquisition_method: str
    backend_root: str
    server_binary: str
    cli_binary: str | None
    configured_at: str

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "HostBackendInstallation":
        """Decode a backend installation from JSON."""
        return cls(
            backend=_require_string(payload, "backend"),
            acquisition_method=_require_string(payload, "acquisition_method"),
            backend_root=_require_string(payload, "backend_root"),
            server_binary=_require_string(payload, "server_binary"),
            cli_binary=_optional_string(payload, "cli_binary"),
            configured_at=_require_string(payload, "configured_at"),
        )

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "backend": self.backend,
            "acquisition_method": self.acquisition_method,
            "backend_root": self.backend_root,
            "server_binary": self.server_binary,
            "configured_at": self.configured_at,
        }
        if self.cli_binary is not None:
            payload["cli_binary"] = self.cli_binary
        return payload


@dataclass(frozen=True)
class HostBackendProcess:
    """Persisted backend-process record."""

    backend: str
    status: str
    pid: int
    command: tuple[str, ...]
    bind_host: str
    port: int
    model: str
    artifact_path: str
    server_binary: str
    log_path: str
    started_at: str
    stopped_at: str | None = None
    exit_code: int | None = None

    @property
    def base_url(self) -> str:
        """Return the northbound URL for the managed backend process."""
        return f"http://{self.bind_host}:{self.port}"

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "HostBackendProcess":
        """Decode one backend-process record from JSON."""
        return cls(
            backend=_require_string(payload, "backend"),
            status=_require_string(payload, "status"),
            pid=_require_int(payload, "pid"),
            command=_require_string_tuple(payload, "command"),
            bind_host=_require_string(payload, "bind_host"),
            port=_require_int(payload, "port"),
            model=_require_string(payload, "model"),
            artifact_path=_require_string(payload, "artifact_path"),
            server_binary=_require_string(payload, "server_binary"),
            log_path=_require_string(payload, "log_path"),
            started_at=_require_string(payload, "started_at"),
            stopped_at=_optional_string(payload, "stopped_at"),
            exit_code=_optional_int(payload, "exit_code"),
        )

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "backend": self.backend,
            "status": self.status,
            "pid": self.pid,
            "command": list(self.command),
            "bind_host": self.bind_host,
            "port": self.port,
            "base_url": self.base_url,
            "model": self.model,
            "artifact_path": self.artifact_path,
            "server_binary": self.server_binary,
            "log_path": self.log_path,
            "started_at": self.started_at,
        }
        if self.stopped_at is not None:
            payload["stopped_at"] = self.stopped_at
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        return payload


@dataclass(frozen=True)
class HostControlPlaneProcess:
    """Persisted control-plane process record."""

    status: str
    pid: int
    command: tuple[str, ...]
    bind_host: str
    port: int
    log_path: str
    started_at: str
    stopped_at: str | None = None
    exit_code: int | None = None

    @property
    def base_url(self) -> str:
        """Return the northbound URL for the control-plane process."""
        return f"http://{self.bind_host}:{self.port}"

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "HostControlPlaneProcess":
        """Decode one control-plane process record from JSON."""
        return cls(
            status=_require_string(payload, "status"),
            pid=_require_int(payload, "pid"),
            command=_require_string_tuple(payload, "command"),
            bind_host=_require_string(payload, "bind_host"),
            port=_require_int(payload, "port"),
            log_path=_require_string(payload, "log_path"),
            started_at=_require_string(payload, "started_at"),
            stopped_at=_optional_string(payload, "stopped_at"),
            exit_code=_optional_int(payload, "exit_code"),
        )

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "status": self.status,
            "pid": self.pid,
            "command": list(self.command),
            "bind_host": self.bind_host,
            "port": self.port,
            "base_url": self.base_url,
            "log_path": self.log_path,
            "started_at": self.started_at,
        }
        if self.stopped_at is not None:
            payload["stopped_at"] = self.stopped_at
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        return payload


@dataclass(frozen=True)
class InstalledModelRecord:
    """Record of an installed host-side model artifact."""

    model: str
    source: str
    backend: str
    acquisition_method: str
    artifact_path: str
    size_bytes: int
    sha256: str
    installed_at: str
    receipt_path: str
    status: str = "installed"

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "InstalledModelRecord":
        """Decode an installed-model record from JSON."""
        return cls(
            model=_require_string(payload, "model"),
            source=_require_string(payload, "source"),
            backend=_require_string(payload, "backend"),
            acquisition_method=_require_string(payload, "acquisition_method"),
            artifact_path=_require_string(payload, "artifact_path"),
            size_bytes=_require_int(payload, "size_bytes"),
            sha256=_require_string(payload, "sha256"),
            installed_at=_require_string(payload, "installed_at"),
            receipt_path=_require_string(payload, "receipt_path"),
            status=_require_string(payload, "status"),
        )

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "model": self.model,
            "source": self.source,
            "backend": self.backend,
            "acquisition_method": self.acquisition_method,
            "artifact_path": self.artifact_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "installed_at": self.installed_at,
            "receipt_path": self.receipt_path,
            "status": self.status,
        }


@dataclass(frozen=True)
class HostRuntimeState:
    """Current host runtime summary."""

    schema_version: str
    backend: str
    backend_policy: str
    model_source_policy: str
    active_model: str | None
    active_source: str | None
    activation_state: str
    installed_models: tuple[InstalledModelRecord, ...]
    backend_installation: HostBackendInstallation | None = None
    backend_status: str = "missing"
    backend_process: HostBackendProcess | None = None
    backend_process_status: str = "not_started"
    control_plane_process: HostControlPlaneProcess | None = None
    control_plane_process_status: str = "not_started"
    supported_sources: tuple[str, ...] = SUPPORTED_MODEL_SOURCES

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "backend_policy": self.backend_policy,
            "model_source_policy": self.model_source_policy,
            "active_model": self.active_model,
            "active_source": self.active_source,
            "activation_state": self.activation_state,
            "backend_status": self.backend_status,
            "backend_process_status": self.backend_process_status,
            "control_plane_process_status": self.control_plane_process_status,
            "installed_models": [record.as_dict() for record in self.installed_models],
            "supported_sources": list(self.supported_sources),
        }
        if self.backend_installation is not None:
            payload["backend_installation"] = self.backend_installation.as_dict()
        if self.backend_process is not None:
            payload["backend_process"] = self.backend_process.as_dict()
        if self.control_plane_process is not None:
            payload["control_plane_process"] = self.control_plane_process.as_dict()
        return payload


class HostStateStore:
    """JSON-backed store for host models, adopted backend, and activation state."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.paths = HostStatePaths.from_project_root(self.project_root)

    def ensure_storage(self) -> None:
        """Create the host-state directories if they do not exist."""
        self.paths.host_dir.mkdir(parents=True, exist_ok=True)
        self.paths.model_receipts_dir.mkdir(parents=True, exist_ok=True)
        self.paths.managed_backends_dir.mkdir(parents=True, exist_ok=True)
        self.paths.managed_models_dir.mkdir(parents=True, exist_ok=True)
        self.paths.host_logs_dir.mkdir(parents=True, exist_ok=True)
        self.paths.responses_state_dir.mkdir(parents=True, exist_ok=True)

    def list_installed_models(self) -> tuple[InstalledModelRecord, ...]:
        """Return installed models sorted by name."""
        payload = load_json_object(self.paths.installed_models_path)
        if not payload:
            return ()
        records_payload = payload.get("models")
        if not isinstance(records_payload, list):
            raise HostStateError(f"{self.paths.installed_models_path} must contain a 'models' list")
        records = [
            _refresh_installed_model_record(InstalledModelRecord.from_dict(entry))
            for entry in records_payload
            if isinstance(entry, dict)
        ]
        return tuple(sorted(records, key=lambda record: record.model))

    def install_model(
        self,
        source_model: SourceModel,
        *,
        acquisition_source: str,
        acquisition_method: str,
        artifact_path: Path,
        size_bytes: int,
        sha256: str,
    ) -> tuple[InstalledModelRecord, bool]:
        """Persist an installed-model receipt and inventory record."""
        self.ensure_storage()
        existing_records = {record.model: record for record in self.list_installed_models()}
        installed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        receipt_path = self.paths.receipt_path(source_model.name)
        normalized_artifact_path = artifact_path.expanduser().resolve()
        record = InstalledModelRecord(
            model=source_model.name,
            source=acquisition_source,
            backend=source_model.backend,
            acquisition_method=acquisition_method,
            artifact_path=str(normalized_artifact_path),
            size_bytes=size_bytes,
            sha256=sha256,
            installed_at=installed_at,
            receipt_path=str(receipt_path),
        )

        receipt_payload = {
            "schema_version": CURRENT_HOST_STATE_SCHEMA_VERSION,
            "model": source_model.name,
            "source": acquisition_source,
            "backend": source_model.backend,
            "summary": source_model.summary,
            "context_window": source_model.context_window,
            "quantization": source_model.quantization,
            "tags": list(source_model.tags),
            "acquisition_method": acquisition_method,
            "artifact_path": str(normalized_artifact_path),
            "size_bytes": size_bytes,
            "sha256": sha256,
            "installed_at": installed_at,
            "status": record.status,
        }
        if source_model.source != acquisition_source:
            receipt_payload["catalog_source"] = source_model.source
        write_json_atomic(receipt_path, receipt_payload)

        created = source_model.name not in existing_records
        existing_records[source_model.name] = record
        inventory_payload = {
            "schema_version": CURRENT_HOST_STATE_SCHEMA_VERSION,
            "models": [entry.as_dict() for entry in sorted(existing_records.values(), key=lambda item: item.model)],
        }
        write_json_atomic(self.paths.installed_models_path, inventory_payload)
        return record, created

    def load_backend_installation(self) -> HostBackendInstallation | None:
        """Load the adopted backend installation if present."""
        payload = load_json_object(self.paths.backend_installation_path)
        if not payload:
            return None
        return HostBackendInstallation.from_dict(payload)

    def save_backend_installation(self, installation: HostBackendInstallation) -> bool:
        """Persist the adopted backend installation record."""
        self.ensure_storage()
        created = not self.paths.backend_installation_path.exists()
        payload = installation.as_dict()
        payload["schema_version"] = CURRENT_HOST_STATE_SCHEMA_VERSION
        write_json_atomic(self.paths.backend_installation_path, payload)
        return created

    def load_backend_process(self) -> HostBackendProcess | None:
        """Load the persisted backend-process record if present."""
        payload = load_json_object(self.paths.backend_process_path)
        if not payload:
            return None
        return HostBackendProcess.from_dict(payload)

    def save_backend_process(self, process: HostBackendProcess) -> bool:
        """Persist the current backend-process record."""
        self.ensure_storage()
        created = not self.paths.backend_process_path.exists()
        payload = process.as_dict()
        payload["schema_version"] = CURRENT_HOST_STATE_SCHEMA_VERSION
        write_json_atomic(self.paths.backend_process_path, payload)
        return created

    def load_control_plane_process(self) -> HostControlPlaneProcess | None:
        """Load the persisted control-plane process record if present."""
        payload = load_json_object(self.paths.control_plane_process_path)
        if not payload:
            return None
        return HostControlPlaneProcess.from_dict(payload)

    def save_control_plane_process(self, process: HostControlPlaneProcess) -> bool:
        """Persist the current control-plane process record."""
        self.ensure_storage()
        created = not self.paths.control_plane_process_path.exists()
        payload = process.as_dict()
        payload["schema_version"] = CURRENT_HOST_STATE_SCHEMA_VERSION
        write_json_atomic(self.paths.control_plane_process_path, payload)
        return created

    def activate_model(self, model_name: str) -> HostRuntimeState:
        """Mark one installed model as active."""
        installed_models = {record.model: record for record in self.list_installed_models()}
        try:
            active_record = installed_models[model_name]
        except KeyError as exc:
            raise InstalledModelNotFoundError(f"model '{model_name}' is not installed") from exc

        self.ensure_storage()
        write_json_atomic(
            self.paths.runtime_state_path,
            {
                "schema_version": CURRENT_HOST_STATE_SCHEMA_VERSION,
                "backend": PRIMARY_BACKEND,
                "backend_policy": BACKEND_ACQUISITION_POLICY,
                "model_source_policy": MODEL_SOURCE_POLICY,
                "active_model": active_record.model,
                "active_source": active_record.source,
            },
        )
        return self.load_runtime_state()

    def load_runtime_state(self) -> HostRuntimeState:
        """Return the current host runtime summary."""
        installed_models = self.list_installed_models()
        backend_installation = self.load_backend_installation()
        persisted_backend_process = self.load_backend_process()
        backend_process = _refresh_backend_process_record(persisted_backend_process)
        if backend_process != persisted_backend_process and backend_process is not None:
            self.save_backend_process(backend_process)
        persisted_control_plane_process = self.load_control_plane_process()
        control_plane_process = _refresh_control_plane_process_record(persisted_control_plane_process)
        if control_plane_process != persisted_control_plane_process and control_plane_process is not None:
            self.save_control_plane_process(control_plane_process)
        runtime_payload = load_json_object(self.paths.runtime_state_path)
        active_model = _optional_string(runtime_payload, "active_model")
        active_source = _optional_string(runtime_payload, "active_source")
        active_record = next((record for record in installed_models if record.model == active_model), None)

        if active_model is None:
            activation_state = "inactive"
            active_source = None
        elif active_record is None:
            activation_state = "missing_installation"
        elif not Path(active_record.artifact_path).exists():
            activation_state = "missing_artifact"
            active_source = active_record.source
        else:
            activation_state = "ready"
            active_source = active_record.source

        backend_status = _backend_status(backend_installation)
        return HostRuntimeState(
            schema_version=CURRENT_HOST_STATE_SCHEMA_VERSION,
            backend=_optional_string(runtime_payload, "backend") or PRIMARY_BACKEND,
            backend_policy=_optional_string(runtime_payload, "backend_policy") or BACKEND_ACQUISITION_POLICY,
            model_source_policy=_optional_string(runtime_payload, "model_source_policy") or MODEL_SOURCE_POLICY,
            active_model=active_model,
            active_source=active_source,
            activation_state=activation_state,
            installed_models=installed_models,
            backend_installation=backend_installation,
            backend_status=backend_status,
            backend_process=backend_process,
            backend_process_status=backend_process.status if backend_process is not None else "not_started",
            control_plane_process=control_plane_process,
            control_plane_process_status=(
                control_plane_process.status if control_plane_process is not None else "not_started"
            ),
        )

    def save_response_state(
        self,
        response_id: str,
        model_name: str,
        messages: list[dict[str, object]],
        *,
        retention_limit: int = DEFAULT_RESPONSE_STATE_RETENTION_LIMIT,
    ) -> None:
        """Persist one response conversation state and prune stale entries."""
        if retention_limit < 1:
            raise HostStateError("response-state retention limit must be at least 1")
        self.ensure_storage()
        stored_state = StoredResponseState(
            response_id=response_id,
            model_name=model_name,
            messages=tuple(deepcopy(message) for message in messages),
            updated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
        payload = stored_state.as_dict()
        payload["schema_version"] = CURRENT_HOST_STATE_SCHEMA_VERSION
        write_json_atomic(self.paths.response_state_path(response_id), payload)
        self.prune_response_states(retention_limit=retention_limit)

    def load_response_state(self, response_id: str) -> StoredResponseState | None:
        """Load one persisted response conversation state if present."""
        payload = load_json_object(self.paths.response_state_path(response_id))
        if not payload:
            return None
        return StoredResponseState.from_dict(payload)

    def count_response_states(self) -> int:
        """Return the number of persisted response-state entries."""
        if not self.paths.responses_state_dir.exists():
            return 0
        return sum(1 for path in self.paths.responses_state_dir.glob("*.json") if path.is_file())

    def response_state_summary(self) -> dict[str, object]:
        """Return summary diagnostics for persisted Responses state."""
        return {
            "count": self.count_response_states(),
            "retention_limit": DEFAULT_RESPONSE_STATE_RETENTION_LIMIT,
            "storage_dir": str(self.paths.responses_state_dir),
        }

    def prune_response_states(
        self,
        *,
        retention_limit: int = DEFAULT_RESPONSE_STATE_RETENTION_LIMIT,
    ) -> tuple[str, ...]:
        """Prune persisted response-state entries beyond the configured retention limit."""
        if retention_limit < 1:
            raise HostStateError("response-state retention limit must be at least 1")
        if not self.paths.responses_state_dir.exists():
            return ()

        stored_entries: list[tuple[Path, str]] = []
        for path in self.paths.responses_state_dir.glob("*.json"):
            if not path.is_file():
                continue
            payload = load_json_object(path)
            if payload:
                updated_at = _optional_string(payload, "updated_at")
                stored_entries.append((path, updated_at or ""))
                continue
            stored_entries.append((path, ""))

        if len(stored_entries) <= retention_limit:
            return ()

        stored_entries.sort(
            key=lambda item: (item[1], item[0].stat().st_mtime),
            reverse=True,
        )
        removed_paths: list[str] = []
        for path, _updated_at in stored_entries[retention_limit:]:
            path.unlink(missing_ok=True)
            removed_paths.append(str(path))
        return tuple(removed_paths)


def _backend_status(installation: HostBackendInstallation | None) -> str:
    if installation is None:
        return "missing"
    if not Path(installation.server_binary).exists():
        return "stale"
    if installation.cli_binary is not None and not Path(installation.cli_binary).exists():
        return "stale"
    return "configured"


def _refresh_installed_model_record(record: InstalledModelRecord) -> InstalledModelRecord:
    status = "installed" if Path(record.artifact_path).exists() else "missing_artifact"
    if status == record.status:
        return record
    return replace(record, status=status)


def _refresh_backend_process_record(process: HostBackendProcess | None) -> HostBackendProcess | None:
    if process is None or process.status not in {"running", "starting"}:
        return process
    if _pid_exists(process.pid):
        return process
    return replace(
        process,
        status="exited",
        stopped_at=process.stopped_at or datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def _refresh_control_plane_process_record(
    process: HostControlPlaneProcess | None,
) -> HostControlPlaneProcess | None:
    if process is None or process.status not in {"running", "starting"}:
        return process
    if _pid_exists(process.pid):
        return process
    return replace(
        process,
        status="exited",
        stopped_at=process.stopped_at or datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def _pid_exists(pid: int) -> bool:
    if pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _require_string(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise HostStateError(f"expected non-empty string for field '{field_name}'")
    return value


def _optional_string(payload: dict[str, object], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HostStateError(f"expected string for field '{field_name}'")
    normalized = value.strip()
    return normalized or None


def _require_int(payload: dict[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or value < 0:
        raise HostStateError(f"expected non-negative integer for field '{field_name}'")
    return value


def _optional_int(payload: dict[str, object], field_name: str) -> int | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise HostStateError(f"expected integer for field '{field_name}'")
    return value


def _require_string_tuple(payload: dict[str, object], field_name: str) -> tuple[str, ...]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise HostStateError(f"expected non-empty list of strings for field '{field_name}'")
    return tuple(value)
