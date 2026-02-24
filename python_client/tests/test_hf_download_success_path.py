from __future__ import annotations

from types import SimpleNamespace

from ai_stack.huggingface.client import RepoFile, RepoSnapshot
from ai_stack.stack import hf_downloads


class _FakeHFClient:
    def __init__(self, models_dir):
        self.models_dir = models_dir
        self.failures_by_file = {}
        self.calls_by_file = {}

    def download_file(self, repo_id: str, filename: str, revision: str = "main", local_dir: str | None = None) -> str:
        self.calls_by_file[filename] = self.calls_by_file.get(filename, 0) + 1
        remaining = self.failures_by_file.get(filename, 0)
        if remaining > 0:
            self.failures_by_file[filename] = remaining - 1
            raise RuntimeError(f"transient failure for {filename}")
        return str(self.models_dir / filename.split("/")[-1])


class _FakeRegistry:
    def __init__(self):
        self.register_model_calls = []
        self.register_mmproj_calls = []

    def register_model(self, **kwargs):
        self.register_model_calls.append(kwargs)

    def register_mmproj(self, **kwargs):
        self.register_mmproj_calls.append(kwargs)


def test_download_registers_model_and_mmproj_linkage(tmp_path) -> None:
    snapshot = RepoSnapshot(
        repo_id="org/model",
        revision="main",
        sha="abc123",
        last_modified=None,
        pipeline_tag=None,
        tags=[],
        library_name=None,
        files=[
            RepoFile(path="model-q4_k_m.gguf", size=1024),
            RepoFile(path="mmproj-model-f16.gguf", size=512),
        ],
    )

    cfg = SimpleNamespace(paths=SimpleNamespace(models_dir=tmp_path))
    registry = _FakeRegistry()
    hf_client = _FakeHFClient(models_dir=tmp_path)

    result = hf_downloads.download_from_huggingface(
        config=cfg,
        registry=registry,
        hf_client=hf_client,
        snapshot=snapshot,
        repo_id="org/model",
        download_mmproj=True,
    )

    assert result.success is True
    assert result.model_path.name == "model-q4_k_m.gguf"
    assert result.mmproj_path is not None
    assert result.mmproj_path.name == "mmproj-model-f16.gguf"

    assert len(registry.register_model_calls) == 1
    assert registry.register_model_calls[0]["mmproj_path"].name == "mmproj-model-f16.gguf"

    assert len(registry.register_mmproj_calls) == 1
    assert registry.register_mmproj_calls[0]["for_models"] == ["model-q4_k_m.gguf"]


def test_download_retries_transient_model_download_error(tmp_path) -> None:
    snapshot = RepoSnapshot(
        repo_id="org/model",
        revision="main",
        sha="abc123",
        last_modified=None,
        pipeline_tag=None,
        tags=[],
        library_name=None,
        files=[RepoFile(path="model-q4_k_m.gguf", size=1024)],
    )

    cfg = SimpleNamespace(paths=SimpleNamespace(models_dir=tmp_path))
    registry = _FakeRegistry()
    hf_client = _FakeHFClient(models_dir=tmp_path)
    hf_client.failures_by_file["model-q4_k_m.gguf"] = 2

    result = hf_downloads.download_from_huggingface(
        config=cfg,
        registry=registry,
        hf_client=hf_client,
        snapshot=snapshot,
        repo_id="org/model",
    )

    assert result.success is True
    assert hf_client.calls_by_file["model-q4_k_m.gguf"] == 3
    assert len(registry.register_model_calls) == 1


def test_download_returns_failure_after_retry_exhaustion(tmp_path) -> None:
    snapshot = RepoSnapshot(
        repo_id="org/model",
        revision="main",
        sha="abc123",
        last_modified=None,
        pipeline_tag=None,
        tags=[],
        library_name=None,
        files=[RepoFile(path="model-q4_k_m.gguf", size=1024)],
    )

    cfg = SimpleNamespace(paths=SimpleNamespace(models_dir=tmp_path))
    registry = _FakeRegistry()
    hf_client = _FakeHFClient(models_dir=tmp_path)
    hf_client.failures_by_file["model-q4_k_m.gguf"] = 5

    result = hf_downloads.download_from_huggingface(
        config=cfg,
        registry=registry,
        hf_client=hf_client,
        snapshot=snapshot,
        repo_id="org/model",
    )

    assert result.success is False
    assert result.error is not None
    assert "Failed to download model file" in result.error
    assert hf_client.calls_by_file["model-q4_k_m.gguf"] == 3
    assert len(registry.register_model_calls) == 0


def test_get_hf_max_workers_defaults_and_bounds(monkeypatch) -> None:
    monkeypatch.delenv("AI_STACK_HF_MAX_WORKERS", raising=False)
    assert hf_downloads.get_hf_max_workers() == 1

    monkeypatch.setenv("AI_STACK_HF_MAX_WORKERS", "2")
    assert hf_downloads.get_hf_max_workers() == 2

    monkeypatch.setenv("AI_STACK_HF_MAX_WORKERS", "0")
    assert hf_downloads.get_hf_max_workers() == 1

    monkeypatch.setenv("AI_STACK_HF_MAX_WORKERS", "99")
    assert hf_downloads.get_hf_max_workers() == hf_downloads.MAX_HF_MAX_WORKERS

    monkeypatch.setenv("AI_STACK_HF_MAX_WORKERS", "not-a-number")
    assert hf_downloads.get_hf_max_workers() == 1


def test_parallel_download_failure_prefers_model_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_STACK_HF_MAX_WORKERS", "2")

    snapshot = RepoSnapshot(
        repo_id="org/model",
        revision="main",
        sha="abc123",
        last_modified=None,
        pipeline_tag=None,
        tags=[],
        library_name=None,
        files=[
            RepoFile(path="model-q4_k_m.gguf", size=1024),
            RepoFile(path="mmproj-model-f16.gguf", size=512),
        ],
    )

    cfg = SimpleNamespace(paths=SimpleNamespace(models_dir=tmp_path))
    registry = _FakeRegistry()
    hf_client = _FakeHFClient(models_dir=tmp_path)
    hf_client.failures_by_file["model-q4_k_m.gguf"] = 5
    hf_client.failures_by_file["mmproj-model-f16.gguf"] = 5

    result = hf_downloads.download_from_huggingface(
        config=cfg,
        registry=registry,
        hf_client=hf_client,
        snapshot=snapshot,
        repo_id="org/model",
        download_mmproj=True,
    )

    assert result.success is False
    assert result.error is not None
    assert "Failed to download model file" in result.error
    assert "model-q4_k_m.gguf" in result.error
