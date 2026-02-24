from __future__ import annotations

from ai_stack.huggingface.client import RepoFile, RepoSnapshot
from ai_stack.huggingface.metadata import derive_model_metadata
from ai_stack.huggingface.resolver import parse_quant_from_filename, resolve_download


def _snapshot(*paths: str) -> RepoSnapshot:
    return RepoSnapshot(
        repo_id="Qwen/Qwen2.5-7B-Instruct-GGUF",
        revision="main",
        sha="abc123",
        last_modified=None,
        pipeline_tag=None,
        tags=[],
        library_name=None,
        files=[RepoFile(path=p, size=1024 * 1024 * 100) for p in paths],
    )


def test_parse_quant_from_filename() -> None:
    assert parse_quant_from_filename("foo/bar/model.Q4_K_M.gguf") == "Q4_K_M"
    assert parse_quant_from_filename("foo/bar/model.iq4_nl.gguf") == "IQ4_NL"
    assert parse_quant_from_filename("foo/bar/model.q8_0.gguf") == "Q8_0"
    assert parse_quant_from_filename("foo/bar/model.gguf") is None


def test_resolver_prefers_cli_quant_when_available() -> None:
    snap = _snapshot(
        "qwen2.5-7b-instruct-q4_k_m.gguf",
        "qwen2.5-7b-instruct-q5_k_m.gguf",
    )
    resolved = resolve_download(snap, preferred_quants=["Q5_K_M"])
    assert resolved.model_file.path == "qwen2.5-7b-instruct-q5_k_m.gguf"


def test_resolver_uses_ranked_quant_fallback() -> None:
    snap = _snapshot(
        "qwen2.5-7b-instruct-q8_0.gguf",
        "qwen2.5-7b-instruct-iq4_nl.gguf",
    )
    resolved = resolve_download(snap, preferred_quants=[])
    assert resolved.model_file.path == "qwen2.5-7b-instruct-iq4_nl.gguf"


def test_derived_metadata_contains_phase_b_fields() -> None:
    model_file = RepoFile(path="Qwen2.5-7B-Instruct-Q4_K_M.gguf", size=8 * 1024 * 1024 * 1024)
    derived = derive_model_metadata(
        repo_id="Qwen/Qwen2.5-7B-Instruct-GGUF",
        model_file=model_file,
    )
    assert derived["family"] == "Qwen2.5-7B-Instruct"
    assert derived["quant"] == "Q4_K_M"
    assert derived["parameter_scale"] == "7B"
    assert derived["model_size"] is not None
