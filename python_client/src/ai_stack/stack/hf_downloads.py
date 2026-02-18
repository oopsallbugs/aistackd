"""Hugging Face download orchestration helpers for SetupManager."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse

from ai_stack.core.exceptions import DownloadError
from ai_stack.huggingface.metadata import derive_model_metadata
from ai_stack.huggingface.resolver import DEFAULT_QUANT_RANKING, resolve_download


def normalize_hf_repo_id(repo_input: str) -> str:
    """
    Accept either:
    - namespace/repo
    - https://huggingface.co/namespace/repo[/...]
    and normalize to namespace/repo.
    """
    value = (repo_input or "").strip()
    if not value:
        raise DownloadError("Repo cannot be empty. Use format: namespace/repo")

    if "://" not in value:
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
        return f"{parts[1]}/{parts[2]}"

    return f"{parts[0]}/{parts[1]}"


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
        print(f"🧠 HF cache miss: {repo_id}@{revision} (fetching snapshot)")
        snap = hf_client.get_snapshot(repo_id=repo_id, revision=revision)
        hf_cache.put(snap)
        return snap

    try:
        remote_sha = hf_client.get_repo_sha(repo_id=repo_id, revision=revision)
    except (OSError, RuntimeError, TimeoutError, ValueError):
        # Intentional broad fallback domain: if SHA check cannot be trusted,
        # reuse cached snapshot instead of failing the command.
        record_cache_event("fallback")
        print(f"🧠 HF cache fallback: {repo_id}@{revision} (SHA check failed, using cached snapshot)")
        hf_cache.touch(repo_id=repo_id, revision=revision)
        return cached.snapshot

    cached_sha = cached.sha or cached.snapshot.sha
    sha_changed = bool(remote_sha) and remote_sha != cached_sha
    sha_missing_locally = bool(remote_sha) and not cached_sha

    if sha_changed or sha_missing_locally:
        record_cache_event("refresh")
        print(f"🧠 HF cache refresh: {repo_id}@{revision} (SHA changed)")
        snap = hf_client.get_snapshot(repo_id=repo_id, revision=revision)
        hf_cache.put(snap)
        return snap

    record_cache_event("hit")
    print(f"🧠 HF cache hit: {repo_id}@{revision} (SHA unchanged)")
    hf_cache.touch(repo_id=repo_id, revision=revision)
    return cached.snapshot


def list_huggingface_files(*, snapshot) -> None:
    """List available files in a HuggingFace repo (GGUF + mmproj)."""
    print(f"\n📦 {snapshot.repo_id}")
    if snapshot.pipeline_tag:
        print(f"   Type: {snapshot.pipeline_tag}")
    if snapshot.tags:
        print(f"   Tags: {', '.join(snapshot.tags[:8])}{'...' if len(snapshot.tags) > 8 else ''}")
    if snapshot.sha:
        print(f"   SHA: {snapshot.sha[:12]}")

    ggufs = snapshot.gguf_files
    mmprojs = snapshot.mmproj_files

    if ggufs:
        print("\n📋 Available GGUF files:")
        for index, file in enumerate(ggufs[:10], 1):
            size_str = f" ({file.size // 1024 // 1024} MB)" if file.size else ""
            print(f"  {index}. {file.path}{size_str}")
        if len(ggufs) > 10:
            print(f"  ... and {len(ggufs) - 10} more")
    else:
        print("\n❌ No GGUF files found.")

    if mmprojs:
        print("\n🖼️  MMproj files available:")
        for file in mmprojs:
            size_str = f" ({file.size // 1024 // 1024} MB)" if file.size else ""
            print(f"  • {file.path}{size_str}")


def download_from_huggingface(
    *,
    config,
    registry,
    hf_client,
    snapshot,
    repo_id: str,
    filename: Optional[str] = None,
    download_mmproj: bool = False,
    quant_preference: Optional[str] = None,
) -> bool:
    ggufs = snapshot.gguf_files
    if not ggufs:
        print(f"❌ No GGUF files found in {repo_id}")
        return False

    if filename:
        match = next((file for file in snapshot.files if file.path == filename), None)
        if not match:
            print(f"❌ File not found in repo: {filename}")
            print("Tip: use --list to see available files.")
            return False
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
        print(f"\n📝 Auto-selected: {model_file.path}")
        if quant_preference:
            print(f"   Quant preference: {quant_preference.upper()}")

    models_dir = str(config.paths.models_dir)
    model_local_path = Path(
        hf_client.download_file(repo_id, model_file.path, revision=snapshot.revision, local_dir=models_dir)
    )

    mmproj_local_path: Optional[Path] = None
    if mmproj_file:
        print(f"🖼️  Downloading MMproj: {mmproj_file.path}")
        mmproj_local_path = Path(
            hf_client.download_file(repo_id, mmproj_file.path, revision=snapshot.revision, local_dir=models_dir)
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

    print("\n✅ Download complete!")
    print(f"   Model: {model_local_path.name}")
    if mmproj_local_path:
        print(f"   MMproj: {mmproj_local_path.name}")

    print("\n📋 To start the server:")
    print(f"   server-start {model_local_path.name}")

    return True


__all__ = [
    "download_from_huggingface",
    "get_hf_snapshot",
    "list_huggingface_files",
    "normalize_hf_repo_id",
]
