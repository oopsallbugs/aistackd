"""Repo-owned control-plane admin helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

from aistackd.models.acquisition import (
    DEFAULT_HUGGING_FACE_CLI,
    ModelAcquisitionError,
    acquire_managed_model_artifact,
    parse_hugging_face_url,
)
from aistackd.models.selection import derive_model_name_from_artifact_name, infer_quantization_from_artifact_name
from aistackd.models.sources import (
    FALLBACK_MODEL_SOURCE,
    LOCAL_MODEL_SOURCE,
    PRIMARY_MODEL_SOURCE,
    SUPPORTED_MODEL_SOURCES,
    ModelSourceError,
    SourceModel,
    local_source_model,
    recommend_models,
    resolve_source_model,
    search_models,
)
from aistackd.runtime.hardware import LLMFIT_BINARY_NAME
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostStateError, HostStateStore, InstalledModelNotFoundError


@dataclass(frozen=True)
class AdminApiError(RuntimeError):
    """Typed admin API error for control-plane request handling."""

    status: HTTPStatus
    message: str
    error_type: str = "invalid_request_error"

    def to_payload(self) -> dict[str, object]:
        return {"error": {"message": self.message, "type": self.error_type}}


def parse_optional_json_request_body(body: bytes) -> dict[str, object]:
    """Decode one optional JSON request body into an object payload."""
    if not body.strip():
        return {}
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdminApiError(HTTPStatus.BAD_REQUEST, f"invalid JSON request body: {exc}") from exc
    if not isinstance(decoded, dict):
        raise AdminApiError(HTTPStatus.BAD_REQUEST, "request body must be a JSON object")
    return decoded


def build_runtime_admin_payload(store: HostStateStore, service: HostServiceConfig) -> dict[str, object]:
    """Build one runtime-inspection payload for the admin API."""
    return {
        "runtime": store.load_runtime_state().to_dict(),
        "service": service.normalized().to_dict(),
        "responses_state": store.response_state_summary(),
    }


def search_models_admin(payload: dict[str, object]) -> dict[str, object]:
    """Search the live llmfit catalog for the admin API."""
    query = _optional_string(payload, "query")
    llmfit_binary = _string_or_default(payload.get("llmfit_binary"), default=LLMFIT_BINARY_NAME)
    try:
        models = search_models(query, llmfit_binary=llmfit_binary)
    except (ModelSourceError, ValueError) as exc:
        raise AdminApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    return {
        "query": query,
        "source": PRIMARY_MODEL_SOURCE,
        "models": [model.as_dict() for model in models],
    }


def recommend_models_admin(payload: dict[str, object]) -> dict[str, object]:
    """Return llmfit recommendations for the admin API."""
    llmfit_binary = _string_or_default(payload.get("llmfit_binary"), default=LLMFIT_BINARY_NAME)
    try:
        models = recommend_models(llmfit_binary=llmfit_binary)
    except (ModelSourceError, ValueError) as exc:
        raise AdminApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    return {
        "source": PRIMARY_MODEL_SOURCE,
        "models": [model.as_dict() for model in models],
    }


def install_model_admin(project_root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Install one model into managed host state through the admin API."""
    source = _optional_string(payload, "source")
    if source is not None and source not in SUPPORTED_MODEL_SOURCES:
        raise AdminApiError(
            HTTPStatus.BAD_REQUEST,
            f"unsupported model source '{source}'; expected one of: {', '.join(SUPPORTED_MODEL_SOURCES)}",
        )

    explicit_gguf_path = _optional_path(payload, "gguf_path")
    local_roots = _path_list(payload.get("local_roots"), field_name="local_roots")
    hugging_face_cli = _string_or_default(payload.get("hf_cli"), default=DEFAULT_HUGGING_FACE_CLI)
    llmfit_binary = _string_or_default(payload.get("llmfit_binary"), default=LLMFIT_BINARY_NAME)
    llmfit_quant = _optional_string(payload, "quant")
    llmfit_budget_gb = _optional_positive_number(payload.get("budget_gb"), field_name="budget_gb")
    activate = _bool_or_default(payload.get("activate"), field_name="activate", default=False)

    try:
        hf_repo, hf_file = _resolve_hugging_face_inputs(payload)
        requested_model_name = _resolve_requested_model_name(
            _optional_string(payload, "model"),
            gguf_path=explicit_gguf_path,
            hf_file=hf_file,
        )
        source_model = _resolve_install_source_model(
            requested_model_name,
            source=source,
            gguf_path=explicit_gguf_path,
            llmfit_binary=llmfit_binary,
            prefer_hugging_face=hf_repo is not None,
        )
        acquisition = acquire_managed_model_artifact(
            project_root,
            source_model,
            explicit_gguf_path=explicit_gguf_path,
            local_roots=local_roots,
            preferred_source=source,
            hugging_face_repo=hf_repo,
            hugging_face_file=hf_file,
            hugging_face_cli=hugging_face_cli,
            llmfit_binary=llmfit_binary,
            llmfit_quant=llmfit_quant,
            llmfit_budget_gb=llmfit_budget_gb,
        )
        store = HostStateStore(project_root)
        record, created = store.install_model(
            source_model,
            acquisition_source=acquisition.source,
            acquisition_method=acquisition.acquisition_method,
            artifact_path=Path(acquisition.artifact_path),
            size_bytes=acquisition.size_bytes,
            sha256=acquisition.sha256,
        )
        runtime_state = store.activate_model(record.model) if activate else store.load_runtime_state()
    except (HostStateError, InstalledModelNotFoundError, ModelAcquisitionError, ModelSourceError, ValueError) as exc:
        raise AdminApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    action = "installed" if created else "updated"
    return {
        "action": action,
        "model": record.as_dict(),
        "active_model": runtime_state.active_model,
        "activation_state": runtime_state.activation_state,
        "acquisition": acquisition.to_dict(),
    }


def activate_model_admin(project_root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Activate one installed model through the admin API."""
    model_name = _required_string(payload, "model")
    try:
        runtime_state = HostStateStore(project_root).activate_model(model_name)
    except (HostStateError, InstalledModelNotFoundError) as exc:
        raise AdminApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    return {
        "action": "activated",
        "runtime": runtime_state.to_dict(),
    }


def _resolve_hugging_face_inputs(payload: dict[str, object]) -> tuple[str | None, str | None]:
    hf_url = _optional_string(payload, "hf_url")
    hf_repo = _optional_string(payload, "hf_repo")
    hf_file = _optional_string(payload, "hf_file")
    if hf_url and (hf_repo or hf_file):
        raise ModelAcquisitionError("use either hf_url or the hf_repo/hf_file pair, not both")
    if hf_url:
        reference = parse_hugging_face_url(hf_url)
        if reference.filename is None:
            raise ModelAcquisitionError(
                "Hugging Face URL does not identify a GGUF file; provide hf_file or a file-specific URL"
            )
        return reference.repo, reference.filename
    if bool(hf_repo) != bool(hf_file):
        raise ModelAcquisitionError("Hugging Face fallback requires both hf_repo and hf_file")
    return hf_repo, hf_file


def _resolve_requested_model_name(
    model_name: str | None,
    *,
    gguf_path: Path | None,
    hf_file: str | None,
) -> str:
    if model_name is not None:
        return model_name
    if gguf_path is not None:
        return derive_model_name_from_artifact_name(gguf_path.name)
    if hf_file is not None:
        return derive_model_name_from_artifact_name(Path(hf_file).name)
    raise ModelAcquisitionError("model is required unless gguf_path or hf_url provides a GGUF filename")


def _resolve_install_source_model(
    model_name: str,
    *,
    source: str | None,
    gguf_path: Path | None,
    llmfit_binary: str,
    prefer_hugging_face: bool,
) -> SourceModel:
    if prefer_hugging_face:
        quantization = infer_quantization_from_artifact_name(model_name)
        return local_source_model(
            model_name,
            source=FALLBACK_MODEL_SOURCE,
            summary="Hugging Face GGUF install",
            quantization=quantization,
            tags=("hugging-face", "download"),
        )

    match: SourceModel | None = None
    if source in (None, PRIMARY_MODEL_SOURCE):
        try:
            match = resolve_source_model(model_name, source=PRIMARY_MODEL_SOURCE, llmfit_binary=llmfit_binary)
        except ModelSourceError:
            match = None
    if match is not None:
        return match

    quantization = infer_quantization_from_artifact_name(gguf_path.name if gguf_path is not None else model_name)
    synthetic_source = source or LOCAL_MODEL_SOURCE
    return local_source_model(model_name, source=synthetic_source, quantization=quantization)


def _required_string(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise AdminApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, object], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AdminApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a non-empty string when provided")
    return value.strip()


def _string_or_default(value: object, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise AdminApiError(HTTPStatus.BAD_REQUEST, "string-valued admin option must be non-empty when provided")
    return value.strip()


def _optional_path(payload: dict[str, object], field_name: str) -> Path | None:
    value = _optional_string(payload, field_name)
    if value is None:
        return None
    return Path(value).expanduser()


def _path_list(value: object, *, field_name: str) -> tuple[Path, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AdminApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a list of path strings")
    paths: list[Path] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise AdminApiError(HTTPStatus.BAD_REQUEST, f"{field_name} entries must be non-empty path strings")
        paths.append(Path(entry).expanduser())
    return tuple(paths)


def _bool_or_default(value: object, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise AdminApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a boolean when provided")
    return value


def _optional_positive_number(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdminApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a positive number when provided")
    numeric_value = float(value)
    if numeric_value <= 0:
        raise AdminApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a positive number when provided")
    return numeric_value
