"""Hugging Face download orchestration helpers for SetupManager."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse

from ai_stack.core.exceptions import DownloadError
from ai_stack.core.logging import emit_event
from ai_stack.huggingface.client import RepoFile, RepoSnapshot
from ai_stack.huggingface.metadata import derive_model_metadata
from ai_stack.huggingface.resolver import DEFAULT_QUANT_RANKING, resolve_download


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
        snap = hf_client.get_snapshot(repo_id=repo_id, revision=revision)
        hf_cache.put(snap)
        return SnapshotFetchResult(snapshot=snap, cache_event="miss")

    try:
        remote_sha = hf_client.get_repo_sha(repo_id=repo_id, revision=revision)
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
        snap = hf_client.get_snapshot(repo_id=repo_id, revision=revision)
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
    model_local_path = Path(
        hf_client.download_file(repo_id, model_file.path, revision=snapshot.revision, local_dir=models_dir)
    )
    emit_event("hf.download.file.complete", repo_id=repo_id, file=model_file.path, local_path=str(model_local_path))

    mmproj_local_path: Optional[Path] = None
    if mmproj_file:
        mmproj_local_path = Path(
            hf_client.download_file(repo_id, mmproj_file.path, revision=snapshot.revision, local_dir=models_dir)
        )
        emit_event(
            "hf.download.file.complete",
            repo_id=repo_id,
            file=mmproj_file.path,
            local_path=str(mmproj_local_path),
            file_type="mmproj",
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
    "download_from_huggingface",
    "get_hf_snapshot",
    "list_huggingface_files",
    "normalize_hf_repo_id",
]
