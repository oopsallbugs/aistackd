"""Model source adapters and acquisition policy contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aistackd.models.selection import normalize_model_name

PRIMARY_BACKEND = "llama.cpp"
PRIMARY_MODEL_SOURCE = "llmfit"
FALLBACK_MODEL_SOURCE = "hugging_face"
BACKEND_ACQUISITION_POLICY = "prebuilt_first_source_fallback"
MODEL_SOURCE_POLICY = "llmfit_first_hugging_face_fallback"
SUPPORTED_MODEL_SOURCES = (PRIMARY_MODEL_SOURCE, FALLBACK_MODEL_SOURCE)


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


class StaticModelSourceAdapter:
    """Simple deterministic source adapter used for the contract phase."""

    def __init__(self, source_name: str, catalog: Sequence[SourceModel]) -> None:
        self.source_name = source_name
        self._catalog = tuple(catalog)

    def search(self, query: str | None = None, *, recommended_only: bool = False) -> tuple[SourceModel, ...]:
        """Return catalog entries matching the query."""
        matches = [
            model
            for model in self._catalog
            if model.matches_query(query) and (model.recommended or not recommended_only)
        ]
        return tuple(sorted(matches, key=_search_sort_key))

    def resolve(self, model_name: str) -> SourceModel | None:
        """Resolve one model by its exact normalized name."""
        normalized_name = normalize_model_name(model_name).lower()
        for model in self._catalog:
            if model.name.lower() == normalized_name:
                return model
        return None


_LLMFIT_CATALOG = (
    SourceModel(
        name="qwen2.5-coder-7b-instruct-q4-k-m",
        source=PRIMARY_MODEL_SOURCE,
        backend=PRIMARY_BACKEND,
        summary="balanced coding default for local development hosts",
        context_window=32768,
        quantization="q4_k_m",
        recommended_rank=1,
        tags=("coding", "balanced", "local"),
    ),
    SourceModel(
        name="llama-3.1-8b-instruct-q4-k-m",
        source=PRIMARY_MODEL_SOURCE,
        backend=PRIMARY_BACKEND,
        summary="general-purpose instruct model with stable baseline behavior",
        context_window=32768,
        quantization="q4_k_m",
        recommended_rank=2,
        tags=("general", "stable"),
    ),
    SourceModel(
        name="deepseek-r1-distill-qwen-7b-q4-k-m",
        source=PRIMARY_MODEL_SOURCE,
        backend=PRIMARY_BACKEND,
        summary="reasoning-oriented small model for constrained local hosts",
        context_window=32768,
        quantization="q4_k_m",
        tags=("reasoning", "local"),
    ),
)

_HUGGING_FACE_CATALOG = (
    SourceModel(
        name="qwen2.5-coder-7b-instruct-q4-k-m",
        source=FALLBACK_MODEL_SOURCE,
        backend=PRIMARY_BACKEND,
        summary="fallback mirror for the recommended local coding model",
        context_window=32768,
        quantization="q4_k_m",
        recommended_rank=1,
        tags=("coding", "fallback"),
    ),
    SourceModel(
        name="mistral-nemo-instruct-2407-q4-k-m",
        source=FALLBACK_MODEL_SOURCE,
        backend=PRIMARY_BACKEND,
        summary="larger context instruct model available through the fallback source",
        context_window=131072,
        quantization="q4_k_m",
        recommended_rank=2,
        tags=("general", "long-context", "fallback"),
    ),
    SourceModel(
        name="deepseek-r1-distill-qwen-7b-q4-k-m",
        source=FALLBACK_MODEL_SOURCE,
        backend=PRIMARY_BACKEND,
        summary="fallback mirror for a smaller reasoning-oriented model",
        context_window=32768,
        quantization="q4_k_m",
        tags=("reasoning", "fallback"),
    ),
)

MODEL_SOURCE_ADAPTERS = {
    PRIMARY_MODEL_SOURCE: StaticModelSourceAdapter(PRIMARY_MODEL_SOURCE, _LLMFIT_CATALOG),
    FALLBACK_MODEL_SOURCE: StaticModelSourceAdapter(FALLBACK_MODEL_SOURCE, _HUGGING_FACE_CATALOG),
}


def model_source_order(preferred_source: str | None = None) -> tuple[str, ...]:
    """Return the source order implied by the current policy."""
    if preferred_source is None:
        return SUPPORTED_MODEL_SOURCES
    if preferred_source not in MODEL_SOURCE_ADAPTERS:
        raise ValueError(
            f"unsupported model source '{preferred_source}'; expected one of: {', '.join(SUPPORTED_MODEL_SOURCES)}"
        )
    return (preferred_source,)


def iter_model_sources(preferred_source: str | None = None) -> tuple[StaticModelSourceAdapter, ...]:
    """Return model-source adapters in policy order."""
    return tuple(MODEL_SOURCE_ADAPTERS[source_name] for source_name in model_source_order(preferred_source))


def search_models(
    query: str | None = None,
    *,
    source: str | None = None,
    recommended_only: bool = False,
) -> tuple[SourceModel, ...]:
    """Search the configured model-source adapters."""
    results: list[SourceModel] = []
    for adapter in iter_model_sources(source):
        results.extend(adapter.search(query, recommended_only=recommended_only))
    return tuple(results)


def recommend_models(*, source: str | None = None) -> tuple[SourceModel, ...]:
    """Return the recommended model set in source-priority order."""
    return search_models(source=source, recommended_only=True)


def resolve_source_model(model_name: str, *, source: str | None = None) -> SourceModel | None:
    """Resolve one exact model name from the configured sources."""
    for adapter in iter_model_sources(source):
        match = adapter.resolve(model_name)
        if match is not None:
            return match
    return None


def _search_sort_key(model: SourceModel) -> tuple[int, int, str]:
    recommended_rank = model.recommended_rank if model.recommended_rank is not None else 999
    return (recommended_rank, model.context_window * -1, model.name)
