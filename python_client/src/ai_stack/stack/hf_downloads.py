"""Hugging Face download orchestration helpers for SetupManager."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse

from ai_stack.core.exceptions import DownloadError
from ai_stack.core.logging import emit_event
from ai_stack.core.retry import retry_call
from ai_stack.huggingface.client import RepoFile, RepoSnapshot
from ai_stack.huggingface.metadata import derive_model_metadata
from ai_stack.huggingface.resolver import DEFAULT_QUANT_RANKING, resolve_download

DEFAULT_HF_RETRY_ATTEMPTS = 3
DEFAULT_HF_RETRY_BACKOFF_SECONDS = 0.25
DEFAULT_HF_MAX_WORKERS = 1
MAX_HF_MAX_WORKERS = 8


@dataclass
class SnapshotFetchResult:
    snapshot: RepoSnapshot
    cache_event: str


@dataclass
class HfFileListResult:
    repo_id: str
    pipeline_tag: Optional[str]
    tags: List[str]
    sha: Optional[str]
    gguf_files: List[RepoFile]
    mmproj_files: List[RepoFile]
    cache_event: Optional[str] = None


@dataclass
class HfDownloadResult:
    success: bool
    repo_id: str
    model_path: Optional[Path] = None
    mmproj_path: Optional[Path] = None
    selected_model_file: Optional[str] = None
    quant_preference: Optional[str] = None
    error: Optional[str] = None
    cache_event: Optional[str] = None


def get_hf_max_workers() -> int:
    """
    Return bounded worker count for HF file downloads.

    Controlled by AI_STACK_HF_MAX_WORKERS; defaults to 1.
    """
    raw = os.environ.get("AI_STACK_HF_MAX_WORKERS", "").strip()
    if not raw:
        return DEFAULT_HF_MAX_WORKERS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_HF_MAX_WORKERS
    return max(1, min(value, MAX_HF_MAX_WORKERS))


def normalize_hf_repo_id(repo_input: str) -> str:
    """
    Accept either:
    - namespace/repo
    - https://huggingface.co/namespace/repo[/...]
    and normalize to namespace/repo.
    """
    value = (repo_input or "").strip()
    emit_event("hf.repo.normalize.start", repo_input=repo_input)
    if not value:
        raise DownloadError("Repo cannot be empty. Use format: namespace/repo")

    if "://" not in value:
        emit_event("hf.repo.normalize.complete", repo_id=value)
        return value

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    if host not in {"huggingface.co", "www.huggingface.co"}:
        raise DownloadError(f"Unsupported host '{parsed.netloc}'. Expected huggingface.co")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise DownloadError("Could not parse repo from URL. Expected: https://huggingface.co/namespace/repo")

    if parts[0] in {"models", "spaces", "datasets"}:
        if parts[0] != "models":
            raise DownloadError("Only model repos are supported. Use a model URL or namespace/repo.")
        if len(parts) < 3:
            raise DownloadError("Could not parse model repo from URL. Expected: https://huggingface.co/models/namespace/repo")
        repo_id = f"{parts[1]}/{parts[2]}"
        emit_event("hf.repo.normalize.complete", repo_id=repo_id)
        return repo_id

    repo_id = f"{parts[0]}/{parts[1]}"
    emit_event("hf.repo.normalize.complete", repo_id=repo_id)
    return repo_id


def get_hf_snapshot(
    *,
    hf_client,
    hf_cache,
    record_cache_event: Callable[[str], None],
    repo_id: str,
    revision: str = "main",
    retry_attempts: int = DEFAULT_HF_RETRY_ATTEMPTS,
    retry_backoff_seconds: float = DEFAULT_HF_RETRY_BACKOFF_SECONDS,
):
    """
    Get repo snapshot using local cache + SHA validation.

    Cache behavior:
    - miss -> fetch full snapshot and store
    - hit -> fetch remote SHA and refresh only if SHA changed
    - if SHA check fails, fall back to cached snapshot
    """
    cached = hf_cache.get(repo_id=repo_id, revision=revision)
    if cached is None:
        record_cache_event("miss")
        emit_event("hf.snapshot.cache.miss", repo_id=repo_id, revision=revision)
        snap = retry_call(
            operation="hf.get_snapshot",
            attempts=retry_attempts,
            backoff_seconds=retry_backoff_seconds,
            fn=lambda: hf_client.get_snapshot(repo_id=repo_id, revision=revision),
        )
        hf_cache.put(snap)
        return SnapshotFetchResult(snapshot=snap, cache_event="miss")

    try:
        remote_sha = retry_call(
            operation="hf.get_repo_sha",
            attempts=retry_attempts,
            backoff_seconds=retry_backoff_seconds,
            fn=lambda: hf_client.get_repo_sha(repo_id=repo_id, revision=revision),
        )
    except (OSError, RuntimeError, TimeoutError, ValueError):
        # Intentional broad fallback domain: if SHA check cannot be trusted,
        # reuse cached snapshot instead of failing the command.
        record_cache_event("fallback")
        emit_event("hf.snapshot.cache.fallback", repo_id=repo_id, revision=revision)
        hf_cache.touch(repo_id=repo_id, revision=revision)
        return SnapshotFetchResult(snapshot=cached.snapshot, cache_event="fallback")

    cached_sha = cached.sha or cached.snapshot.sha
    sha_changed = bool(remote_sha) and remote_sha != cached_sha
    sha_missing_locally = bool(remote_sha) and not cached_sha

    if sha_changed or sha_missing_locally:
        record_cache_event("refresh")
        emit_event("hf.snapshot.cache.refresh", repo_id=repo_id, revision=revision)
        snap = retry_call(
            operation="hf.get_snapshot",
            attempts=retry_attempts,
            backoff_seconds=retry_backoff_seconds,
            fn=lambda: hf_client.get_snapshot(repo_id=repo_id, revision=revision),
        )
        hf_cache.put(snap)
        return SnapshotFetchResult(snapshot=snap, cache_event="refresh")

    record_cache_event("hit")
    emit_event("hf.snapshot.cache.hit", repo_id=repo_id, revision=revision)
    hf_cache.touch(repo_id=repo_id, revision=revision)
    return SnapshotFetchResult(snapshot=cached.snapshot, cache_event="hit")


def list_huggingface_files(*, snapshot: RepoSnapshot) -> HfFileListResult:
    """Return available files in a HuggingFace repo (GGUF + mmproj)."""
    return HfFileListResult(
        repo_id=snapshot.repo_id,
        pipeline_tag=snapshot.pipeline_tag,
        tags=list(snapshot.tags),
        sha=snapshot.sha,
        gguf_files=list(snapshot.gguf_files),
        mmproj_files=list(snapshot.mmproj_files),
    )


def download_from_huggingface(
    *,
    config,
    registry,
    hf_client,
    snapshot: RepoSnapshot,
    repo_id: str,
    filename: Optional[str] = None,
    download_mmproj: bool = False,
    quant_preference: Optional[str] = None,
    retry_attempts: int = DEFAULT_HF_RETRY_ATTEMPTS,
    retry_backoff_seconds: float = DEFAULT_HF_RETRY_BACKOFF_SECONDS,
) -> HfDownloadResult:
    emit_event(
        "hf.download.resolve.start",
        repo_id=repo_id,
        filename=filename,
        download_mmproj=download_mmproj,
        quant_preference=quant_preference,
    )
    ggufs = snapshot.gguf_files
    if not ggufs:
        emit_event("hf.download.resolve.failed", repo_id=repo_id, reason="no_gguf")
        return HfDownloadResult(
            success=False,
            repo_id=repo_id,
            error=f"No GGUF files found in {repo_id}",
        )

    if filename:
        match = next((file for file in snapshot.files if file.path == filename), None)
        if not match:
            emit_event("hf.download.resolve.failed", repo_id=repo_id, reason="file_not_found", filename=filename)
            return HfDownloadResult(
                success=False,
                repo_id=repo_id,
                error=f"File not found in repo: {filename}",
            )
        model_file = match
        mmproj_file = snapshot.mmproj_files[0] if (download_mmproj and snapshot.mmproj_files) else None
    else:
        preferred_quants: List[str] = []
        if quant_preference:
            preferred_quants.append(quant_preference.upper())
        preferred_quants.extend(DEFAULT_QUANT_RANKING)
        resolved = resolve_download(snapshot, preferred_quants=preferred_quants)
        model_file = resolved.model_file
        mmproj_file = resolved.mmproj_file if download_mmproj else None

    models_dir = str(config.paths.models_dir)
    max_workers = get_hf_max_workers()
    emit_event("hf.download.workers", requested=max_workers)

    class _DownloadFileError(RuntimeError):
        def __init__(self, *, file: RepoFile, file_type: str, cause: Exception):
            super().__init__(str(cause))
            self.file = file
            self.file_type = file_type
            self.cause = cause

    def _download_file(file: RepoFile, operation: str, file_type: str) -> Path:
        try:
            local_path = Path(
                retry_call(
                    operation=operation,
                    attempts=retry_attempts,
                    backoff_seconds=retry_backoff_seconds,
                    fn=lambda: hf_client.download_file(
                        repo_id,
                        file.path,
                        revision=snapshot.revision,
                        local_dir=models_dir,
                    ),
                )
            )
        except (OSError, RuntimeError, TimeoutError, ConnectionError) as exc:
            raise _DownloadFileError(file=file, file_type=file_type, cause=exc) from exc
        emit_event(
            "hf.download.file.complete",
            repo_id=repo_id,
            file=file.path,
            local_path=str(local_path),
            file_type=file_type,
        )
        return local_path

    def _format_download_error(file: RepoFile, file_type: str, exc: Exception) -> str:
        label = "model file" if file_type == "model" else "mmproj file"
        return f"Failed to download {label} '{file.path}': {exc}"

    try:
        if mmproj_file and max_workers > 1:
            worker_count = min(max_workers, 2)
            emit_event("hf.download.parallel.start", repo_id=repo_id, workers=worker_count)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    "model": executor.submit(_download_file, model_file, "hf.download_file.model", "model"),
                    "mmproj": executor.submit(_download_file, mmproj_file, "hf.download_file.mmproj", "mmproj"),
                }
                wait(set(futures.values()))

                # Deterministic failure precedence: model first, then mmproj.
                for file_type in ("model", "mmproj"):
                    error = futures[file_type].exception()
                    if error is not None:
                        emit_event(
                            "hf.download.parallel.failed",
                            level="error",
                            repo_id=repo_id,
                            failed_file_type=file_type,
                            error=str(error),
                        )
                        raise error

                model_local_path = futures["model"].result()
                mmproj_local_path = futures["mmproj"].result()
                emit_event("hf.download.parallel.complete", repo_id=repo_id, workers=worker_count)
        else:
            model_local_path = _download_file(model_file, "hf.download_file.model", "model")
            mmproj_local_path = _download_file(mmproj_file, "hf.download_file.mmproj", "mmproj") if mmproj_file else None
    except _DownloadFileError as exc:
        emit_event(
            "hf.download.file.failed",
            level="error",
            repo_id=repo_id,
            file=exc.file.path,
            file_type=exc.file_type,
            error=str(exc.cause),
        )
        return HfDownloadResult(
            success=False,
            repo_id=repo_id,
            error=_format_download_error(exc.file, exc.file_type, exc.cause),
        )

    registry.register_model(
        path=model_local_path,
        origin="huggingface",
        mmproj_path=mmproj_local_path,
        repo={
            "repo_id": repo_id,
            "revision": snapshot.revision,
            "sha": snapshot.sha,
            "source_url": f"https://huggingface.co/{repo_id}",
        },
        derived=derive_model_metadata(repo_id=repo_id, model_file=model_file),
        save=True,
    )

    if mmproj_local_path:
        registry.register_mmproj(
            path=mmproj_local_path,
            origin="huggingface",
            for_models=[model_local_path.name],
            repo={
                "repo_id": repo_id,
                "revision": snapshot.revision,
                "sha": snapshot.sha,
                "source_url": f"https://huggingface.co/{repo_id}",
            },
            save=True,
        )

    emit_event(
        "hf.download.resolve.complete",
        repo_id=repo_id,
        selected_model_file=model_file.path,
        has_mmproj=bool(mmproj_local_path),
    )
    return HfDownloadResult(
        success=True,
        repo_id=repo_id,
        model_path=model_local_path,
        mmproj_path=mmproj_local_path,
        selected_model_file=model_file.path,
        quant_preference=quant_preference.upper() if quant_preference else None,
    )


__all__ = [
    "HfDownloadResult",
    "HfFileListResult",
    "SnapshotFetchResult",
    "DEFAULT_HF_MAX_WORKERS",
    "DEFAULT_HF_RETRY_ATTEMPTS",
    "DEFAULT_HF_RETRY_BACKOFF_SECONDS",
    "MAX_HF_MAX_WORKERS",
    "download_from_huggingface",
    "get_hf_max_workers",
    "get_hf_snapshot",
    "list_huggingface_files",
    "normalize_hf_repo_id",
]
