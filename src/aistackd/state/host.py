"""Host-side model inventory and activation state."""

from __future__ import annotations

from dataclasses import dataclass
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
CURRENT_HOST_STATE_SCHEMA_VERSION = "v1alpha1"


class HostStateError(RuntimeError):
    """Base exception for host-state operations."""


class InstalledModelNotFoundError(HostStateError):
    """Raised when a requested installed model does not exist."""


@dataclass(frozen=True)
class HostStatePaths:
    """Canonical host-state paths."""

    runtime_state_root: Path
    host_dir: Path
    runtime_state_path: Path
    installed_models_path: Path
    model_receipts_dir: Path

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
        )

    def receipt_path(self, model_name: str) -> Path:
        """Return the receipt path for one installed model."""
        return self.model_receipts_dir / f"{frontend_model_key(model_name)}.json"


@dataclass(frozen=True)
class InstalledModelRecord:
    """Record of an installed host-side model artifact."""

    model: str
    source: str
    backend: str
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
    supported_sources: tuple[str, ...] = SUPPORTED_MODEL_SOURCES

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "backend_policy": self.backend_policy,
            "model_source_policy": self.model_source_policy,
            "active_model": self.active_model,
            "active_source": self.active_source,
            "activation_state": self.activation_state,
            "installed_models": [record.as_dict() for record in self.installed_models],
            "supported_sources": list(self.supported_sources),
        }


class HostStateStore:
    """JSON-backed store for installed host models and activation state."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.paths = HostStatePaths.from_project_root(self.project_root)

    def ensure_storage(self) -> None:
        """Create the host-state directories if they do not exist."""
        self.paths.host_dir.mkdir(parents=True, exist_ok=True)
        self.paths.model_receipts_dir.mkdir(parents=True, exist_ok=True)

    def list_installed_models(self) -> tuple[InstalledModelRecord, ...]:
        """Return installed models sorted by name."""
        payload = load_json_object(self.paths.installed_models_path)
        if not payload:
            return ()
        records_payload = payload.get("models")
        if not isinstance(records_payload, list):
            raise HostStateError(f"{self.paths.installed_models_path} must contain a 'models' list")
        records = [InstalledModelRecord.from_dict(entry) for entry in records_payload if isinstance(entry, dict)]
        return tuple(sorted(records, key=lambda record: record.model))

    def install_model(self, source_model: SourceModel) -> tuple[InstalledModelRecord, bool]:
        """Persist an installed-model receipt and inventory record."""
        self.ensure_storage()
        existing_records = {record.model: record for record in self.list_installed_models()}
        installed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        receipt_path = self.paths.receipt_path(source_model.name)
        record = InstalledModelRecord(
            model=source_model.name,
            source=source_model.source,
            backend=source_model.backend,
            installed_at=installed_at,
            receipt_path=str(receipt_path),
        )

        receipt_payload = {
            "schema_version": CURRENT_HOST_STATE_SCHEMA_VERSION,
            "model": source_model.name,
            "source": source_model.source,
            "backend": source_model.backend,
            "summary": source_model.summary,
            "context_window": source_model.context_window,
            "quantization": source_model.quantization,
            "tags": list(source_model.tags),
            "installed_at": installed_at,
            "status": record.status,
        }
        write_json_atomic(receipt_path, receipt_payload)

        created = source_model.name not in existing_records
        existing_records[source_model.name] = record
        inventory_payload = {
            "schema_version": CURRENT_HOST_STATE_SCHEMA_VERSION,
            "models": [entry.as_dict() for entry in sorted(existing_records.values(), key=lambda item: item.model)],
        }
        write_json_atomic(self.paths.installed_models_path, inventory_payload)
        return record, created

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
        runtime_payload = load_json_object(self.paths.runtime_state_path)
        active_model = _optional_string(runtime_payload, "active_model")
        active_source = _optional_string(runtime_payload, "active_source")

        if active_model is None:
            activation_state = "inactive"
            active_source = None
        elif any(record.model == active_model for record in installed_models):
            activation_state = "ready"
        else:
            activation_state = "missing_installation"

        return HostRuntimeState(
            schema_version=CURRENT_HOST_STATE_SCHEMA_VERSION,
            backend=_optional_string(runtime_payload, "backend") or PRIMARY_BACKEND,
            backend_policy=_optional_string(runtime_payload, "backend_policy") or BACKEND_ACQUISITION_POLICY,
            model_source_policy=_optional_string(runtime_payload, "model_source_policy") or MODEL_SOURCE_POLICY,
            active_model=active_model,
            active_source=active_source,
            activation_state=activation_state,
            installed_models=installed_models,
        )


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

