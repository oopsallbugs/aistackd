"""Model source adapters and acquisition policy contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aistackd.models.llmfit import (
    LlmfitCommandError,
    extract_model_entries,
    model_context_window_from_entry,
    model_name_from_entry,
    model_quantization_from_entry,
    model_summary_from_entry,
    model_tags_from_entry,
    run_llmfit_json_command,
)
from aistackd.models.selection import normalize_model_name

PRIMARY_BACKEND = "llama.cpp"
PRIMARY_MODEL_SOURCE = "llmfit"
FALLBACK_MODEL_SOURCE = "hugging_face"
LOCAL_MODEL_SOURCE = "local"
BACKEND_ACQUISITION_POLICY = "prebuilt_first_source_fallback"
MODEL_SOURCE_POLICY = "llmfit_first_hugging_face_fallback"
SUPPORTED_MODEL_SOURCES = (PRIMARY_MODEL_SOURCE, FALLBACK_MODEL_SOURCE)
LLMFIT_BINARY_NAME = "llmfit"


class ModelSourceError(RuntimeError):
    """Raised when model-source discovery commands cannot complete."""


@dataclass(frozen=True)
class SourceModel:
    """Catalog entry exposed by a model-source adapter."""

    name: str
    source: str
    backend: str
    summary: str
    context_window: int
    quantization: str
    recommended_rank: int | None = None
    tags: tuple[str, ...] = ()

    def matches_query(self, query: str | None) -> bool:
        """Return ``True`` when the model matches a search query."""
        if query is None:
            return True

        normalized_query = normalize_model_name(query).lower()
        if not normalized_query:
            return True

        haystacks = (self.name, self.summary, " ".join(self.tags))
        return any(normalized_query in value.lower() for value in haystacks)

    @property
    def recommended(self) -> bool:
        """Return whether the model is in the recommended set."""
        return self.recommended_rank is not None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "name": self.name,
            "source": self.source,
            "backend": self.backend,
            "summary": self.summary,
            "context_window": self.context_window,
            "quantization": self.quantization,
            "tags": list(self.tags),
            "recommended": self.recommended,
        }
        if self.recommended_rank is not None:
            payload["recommended_rank"] = self.recommended_rank
        return payload


def model_source_order(preferred_source: str | None = None) -> tuple[str, ...]:
    """Return the source order implied by the current policy."""
    if preferred_source is None:
        return SUPPORTED_MODEL_SOURCES
    if preferred_source not in SUPPORTED_MODEL_SOURCES:
        raise ValueError(
            f"unsupported model source '{preferred_source}'; expected one of: {', '.join(SUPPORTED_MODEL_SOURCES)}"
        )
    return (preferred_source,)


def search_models(
    query: str | None = None,
    *,
    llmfit_binary: str = LLMFIT_BINARY_NAME,
    recommended_only: bool = False,
) -> tuple[SourceModel, ...]:
    """Search the live llmfit catalog."""
    if recommended_only:
        models = recommend_models(llmfit_binary=llmfit_binary)
        return tuple(model for model in models if model.matches_query(query))

    subcommand = ("search",)
    if query and query.strip():
        subcommand = ("search", query.strip())
    try:
        _, payload = run_llmfit_json_command(subcommand, llmfit_binary=llmfit_binary)
    except LlmfitCommandError as exc:
        raise ModelSourceError(str(exc)) from exc
    return _parse_llmfit_models(payload, query=query)


def recommend_models(*, llmfit_binary: str = LLMFIT_BINARY_NAME) -> tuple[SourceModel, ...]:
    """Return the policy-ranked llmfit recommendations."""
    try:
        _, payload = run_llmfit_json_command(("recommend",), llmfit_binary=llmfit_binary)
    except LlmfitCommandError as exc:
        raise ModelSourceError(str(exc)) from exc
    return _parse_llmfit_models(payload, recommended=True)


def resolve_source_model(
    model_name: str,
    *,
    source: str | None = None,
    llmfit_binary: str = LLMFIT_BINARY_NAME,
) -> SourceModel | None:
    """Resolve one exact model name from the configured sources."""
    for source_name in model_source_order(source):
        if source_name != PRIMARY_MODEL_SOURCE:
            continue
        matches = search_models(model_name, llmfit_binary=llmfit_binary)
        normalized_name = normalize_model_name(model_name).lower()
        for match in matches:
            if match.name.lower() == normalized_name:
                return match
    return None


def local_source_model(
    model_name: str,
    *,
    source: str = LOCAL_MODEL_SOURCE,
    summary: str = "local GGUF import",
    quantization: str = "unknown",
    context_window: int = 0,
    tags: Sequence[str] = ("local",),
) -> SourceModel:
    """Build a synthetic model descriptor for explicit artifact installs."""
    return SourceModel(
        name=normalize_model_name(model_name),
        source=source,
        backend=PRIMARY_BACKEND,
        summary=summary,
        context_window=context_window,
        quantization=quantization,
        tags=tuple(tags),
    )


def _parse_llmfit_models(
    payload: object,
    *,
    query: str | None = None,
    recommended: bool = False,
) -> tuple[SourceModel, ...]:
    models: list[SourceModel] = []
    for index, entry in enumerate(extract_model_entries(payload), start=1):
        name = model_name_from_entry(entry)
        if name is None:
            continue
        model = SourceModel(
            name=name,
            source=PRIMARY_MODEL_SOURCE,
            backend=PRIMARY_BACKEND,
            summary=model_summary_from_entry(entry),
            context_window=model_context_window_from_entry(entry),
            quantization=model_quantization_from_entry(entry),
            recommended_rank=_recommended_rank(entry, fallback=index if recommended else None),
            tags=model_tags_from_entry(entry),
        )
        if model.matches_query(query):
            models.append(model)
    return tuple(sorted(models, key=_search_sort_key))


def _recommended_rank(entry: dict[str, object], fallback: int | None) -> int | None:
    for key in ("recommended_rank", "rank", "position"):
        value = entry.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return fallback


def _search_sort_key(model: SourceModel) -> tuple[int, int, str]:
    recommended_rank = model.recommended_rank if model.recommended_rank is not None else 999
    return (recommended_rank, model.context_window * -1, model.name)
