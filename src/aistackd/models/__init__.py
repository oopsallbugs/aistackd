"""Model-layer exports."""

from aistackd.models.acquisition import (
    DEFAULT_HUGGING_FACE_CLI,
    ModelAcquisitionAttempt,
    ModelAcquisitionError,
    ModelAcquisitionResult,
    acquire_managed_model_artifact,
    discover_local_gguf,
    iter_local_model_roots,
)
from aistackd.models.selection import (
    SINGLE_ACTIVE_MODEL_POLICY,
    frontend_model_key,
    normalize_model_name,
    validate_model_name,
)
from aistackd.models.sources import (
    BACKEND_ACQUISITION_POLICY,
    FALLBACK_MODEL_SOURCE,
    LOCAL_MODEL_SOURCE,
    MODEL_SOURCE_POLICY,
    MODEL_SOURCE_ADAPTERS,
    PRIMARY_BACKEND,
    PRIMARY_MODEL_SOURCE,
    SUPPORTED_MODEL_SOURCES,
    SourceModel,
    local_source_model,
    recommend_models,
    resolve_source_model,
    search_models,
)

__all__ = [
    "BACKEND_ACQUISITION_POLICY",
    "DEFAULT_HUGGING_FACE_CLI",
    "FALLBACK_MODEL_SOURCE",
    "LOCAL_MODEL_SOURCE",
    "MODEL_SOURCE_POLICY",
    "MODEL_SOURCE_ADAPTERS",
    "ModelAcquisitionAttempt",
    "ModelAcquisitionError",
    "ModelAcquisitionResult",
    "PRIMARY_BACKEND",
    "PRIMARY_MODEL_SOURCE",
    "SINGLE_ACTIVE_MODEL_POLICY",
    "SUPPORTED_MODEL_SOURCES",
    "SourceModel",
    "acquire_managed_model_artifact",
    "discover_local_gguf",
    "frontend_model_key",
    "iter_local_model_roots",
    "local_source_model",
    "normalize_model_name",
    "recommend_models",
    "resolve_source_model",
    "search_models",
    "validate_model_name",
]
