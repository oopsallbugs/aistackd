"""Managed model acquisition and local GGUF adoption helpers."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aistackd.models.selection import frontend_model_key
from aistackd.models.sources import (
    FALLBACK_MODEL_SOURCE,
    LOCAL_MODEL_SOURCE,
    PRIMARY_MODEL_SOURCE,
    SourceModel,
    model_source_order,
)
from aistackd.state.host import HostStatePaths

DEFAULT_HUGGING_FACE_CLI = "hf"
GGUF_FILE_SUFFIX = ".gguf"


@dataclass(frozen=True)
class ModelAcquisitionAttempt:
    """One model-acquisition attempt and its outcome."""

    provider: str
    strategy: str
    ok: bool
    detail: str
    artifact_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "provider": self.provider,
            "strategy": self.strategy,
            "ok": self.ok,
            "detail": self.detail,
        }
        if self.artifact_path is not None:
            payload["artifact_path"] = self.artifact_path
        return payload


@dataclass(frozen=True)
class ModelAcquisitionResult:
    """Result of acquiring one managed GGUF artifact."""

    source: str
    acquisition_method: str
    artifact_path: str
    size_bytes: int
    sha256: str
    attempts: tuple[ModelAcquisitionAttempt, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "source": self.source,
            "acquisition_method": self.acquisition_method,
            "artifact_path": self.artifact_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


class ModelAcquisitionError(RuntimeError):
    """Raised when model acquisition cannot produce a managed GGUF artifact."""


def acquire_managed_model_artifact(
    project_root: Path,
    source_model: SourceModel,
    *,
    explicit_gguf_path: Path | None = None,
    local_roots: tuple[Path, ...] = (),
    preferred_source: str | None = None,
    hugging_face_repo: str | None = None,
    hugging_face_file: str | None = None,
    hugging_face_cli: str = DEFAULT_HUGGING_FACE_CLI,
) -> ModelAcquisitionResult:
    """Acquire a managed model artifact using the configured policy order."""
    paths = HostStatePaths.from_project_root(project_root.resolve())
    attempts: list[ModelAcquisitionAttempt] = []

    if explicit_gguf_path is not None:
        try:
            artifact_path, size_bytes, sha256 = _copy_local_gguf_into_managed_store(
                paths,
                source_model.name,
                explicit_gguf_path,
            )
        except ModelAcquisitionError as exc:
            attempts.append(
                ModelAcquisitionAttempt(
                    provider=LOCAL_MODEL_SOURCE,
                    strategy="explicit_path",
                    ok=False,
                    detail=str(exc),
                )
            )
        else:
            attempts.append(
                ModelAcquisitionAttempt(
                    provider=LOCAL_MODEL_SOURCE,
                    strategy="explicit_path",
                    ok=True,
                    detail="imported explicit GGUF into managed host state",
                    artifact_path=str(artifact_path),
                )
            )
            return ModelAcquisitionResult(
                source=LOCAL_MODEL_SOURCE,
                acquisition_method="explicit_local_gguf",
                artifact_path=str(artifact_path),
                size_bytes=size_bytes,
                sha256=sha256,
                attempts=tuple(attempts),
            )

    local_match = discover_local_gguf(
        source_model.name,
        project_root=project_root,
        local_roots=local_roots,
    )
    if local_match is None:
        attempts.append(
            ModelAcquisitionAttempt(
                provider=LOCAL_MODEL_SOURCE,
                strategy="local_search",
                ok=False,
                detail="no matching GGUF was found under configured local roots",
            )
        )
    else:
        artifact_path, size_bytes, sha256 = _copy_local_gguf_into_managed_store(paths, source_model.name, local_match)
        attempts.append(
            ModelAcquisitionAttempt(
                provider=LOCAL_MODEL_SOURCE,
                strategy="local_search",
                ok=True,
                detail=f"discovered local GGUF at '{local_match}'",
                artifact_path=str(artifact_path),
            )
        )
        return ModelAcquisitionResult(
            source=LOCAL_MODEL_SOURCE,
            acquisition_method="discovered_local_gguf",
            artifact_path=str(artifact_path),
            size_bytes=size_bytes,
            sha256=sha256,
            attempts=tuple(attempts),
        )

    for provider in model_source_order(preferred_source):
        if provider == PRIMARY_MODEL_SOURCE:
            attempts.append(
                ModelAcquisitionAttempt(
                    provider=PRIMARY_MODEL_SOURCE,
                    strategy="provider_download",
                    ok=False,
                    detail="llmfit model acquisition is not wired yet; use --gguf-path, --local-root, or Hugging Face fallback",
                )
            )
            continue

        if provider == FALLBACK_MODEL_SOURCE:
            try:
                artifact_path, size_bytes, sha256 = _acquire_from_hugging_face(
                    paths,
                    source_model.name,
                    repo=hugging_face_repo,
                    filename=hugging_face_file,
                    hugging_face_cli=hugging_face_cli,
                )
            except ModelAcquisitionError as exc:
                attempts.append(
                    ModelAcquisitionAttempt(
                        provider=FALLBACK_MODEL_SOURCE,
                        strategy="provider_download",
                        ok=False,
                        detail=str(exc),
                    )
                )
                continue

            attempts.append(
                ModelAcquisitionAttempt(
                    provider=FALLBACK_MODEL_SOURCE,
                    strategy="provider_download",
                    ok=True,
                    detail=f"downloaded GGUF from Hugging Face repo '{hugging_face_repo}'",
                    artifact_path=str(artifact_path),
                )
            )
            return ModelAcquisitionResult(
                source=FALLBACK_MODEL_SOURCE,
                acquisition_method="hugging_face_download",
                artifact_path=str(artifact_path),
                size_bytes=size_bytes,
                sha256=sha256,
                attempts=tuple(attempts),
            )

    detail = " ; ".join(f"{attempt.provider}/{attempt.strategy}: {attempt.detail}" for attempt in attempts)
    raise ModelAcquisitionError(detail or "no model acquisition attempt was made")


def discover_local_gguf(
    model_name: str,
    *,
    project_root: Path,
    local_roots: tuple[Path, ...] = (),
) -> Path | None:
    """Return the best matching local GGUF path for one model name."""
    target_key = frontend_model_key(model_name)
    candidates: list[tuple[int, int, str, Path]] = []

    for root in iter_local_model_roots(project_root, local_roots=local_roots):
        if not root.exists() or not root.is_dir():
            continue
        for candidate in root.rglob(f"*{GGUF_FILE_SUFFIX}"):
            if not candidate.is_file():
                continue
            score = _local_match_score(candidate, target_key)
            if score is None:
                continue
            candidates.append((score[0], score[1], str(candidate), candidate.resolve()))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


def iter_local_model_roots(project_root: Path, *, local_roots: tuple[Path, ...] = ()) -> tuple[Path, ...]:
    """Return the ordered set of local roots used for GGUF discovery."""
    project = project_root.resolve()
    home = Path.home()
    roots = (
        *(path.expanduser().resolve() for path in local_roots),
        project / "models",
        project / ".models",
        home / "models",
        home / ".cache" / "llmfit",
        home / ".cache" / "huggingface" / "hub",
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return tuple(deduped)


def _copy_local_gguf_into_managed_store(
    paths: HostStatePaths,
    model_name: str,
    source_path: Path,
) -> tuple[Path, int, str]:
    normalized_source = source_path.expanduser().resolve()
    if not normalized_source.exists():
        raise ModelAcquisitionError(f"GGUF path '{normalized_source}' does not exist")
    if not normalized_source.is_file():
        raise ModelAcquisitionError(f"GGUF path '{normalized_source}' is not a file")
    if normalized_source.suffix.lower() != GGUF_FILE_SUFFIX:
        raise ModelAcquisitionError(f"GGUF path '{normalized_source}' must end with '{GGUF_FILE_SUFFIX}'")

    workspace_root = paths.model_workspace_dir(model_name)
    if normalized_source == workspace_root or workspace_root in normalized_source.parents:
        raise ModelAcquisitionError("GGUF import path must not already point inside managed host state")

    _reset_model_workspace(workspace_root)
    artifact_dir = paths.model_artifact_dir(model_name)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    managed_path = artifact_dir / normalized_source.name
    _copy_file_atomic(normalized_source, managed_path)
    size_bytes = managed_path.stat().st_size
    sha256 = _file_sha256(managed_path)
    return managed_path, size_bytes, sha256


def _acquire_from_hugging_face(
    paths: HostStatePaths,
    model_name: str,
    *,
    repo: str | None,
    filename: str | None,
    hugging_face_cli: str,
) -> tuple[Path, int, str]:
    if not repo or not filename:
        raise ModelAcquisitionError("Hugging Face fallback requires both --hf-repo and --hf-file")

    workspace_root = paths.model_workspace_dir(model_name)
    _reset_model_workspace(workspace_root)
    download_root = workspace_root / "downloads" / FALLBACK_MODEL_SOURCE
    download_root.mkdir(parents=True, exist_ok=True)

    command = [
        hugging_face_cli,
        "download",
        repo,
        filename,
        "--local-dir",
        str(download_root),
        "--quiet",
    ]
    downloaded_path = _run_hugging_face_download(command, download_root / filename)
    artifact_dir = paths.model_artifact_dir(model_name)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    managed_path = artifact_dir / downloaded_path.name
    _copy_file_atomic(downloaded_path, managed_path)
    size_bytes = managed_path.stat().st_size
    sha256 = _file_sha256(managed_path)
    return managed_path, size_bytes, sha256


def _run_hugging_face_download(command: list[str], default_path: Path) -> Path:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ModelAcquisitionError(f"Hugging Face download command failed to start: {exc}") from exc

    if completed.returncode != 0:
        detail = _summarize_command_output(completed.stdout, completed.stderr)
        message = f"Hugging Face download failed with exit code {completed.returncode}"
        if detail:
            message += f": {detail}"
        raise ModelAcquisitionError(message)

    stdout = completed.stdout.strip()
    candidate = Path(stdout.splitlines()[-1]).expanduser().resolve() if stdout else default_path.resolve()
    if candidate.exists() and candidate.is_file():
        return candidate
    fallback = default_path.expanduser().resolve()
    if fallback.exists() and fallback.is_file():
        return fallback
    raise ModelAcquisitionError("Hugging Face download did not produce a GGUF artifact")


def _reset_model_workspace(workspace_root: Path) -> None:
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with source.open("rb") as source_handle:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as destination_handle:
                shutil.copyfileobj(source_handle, destination_handle)
                temporary_path = Path(destination_handle.name)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_match_score(candidate: Path, target_key: str) -> tuple[int, int] | None:
    stem_key = frontend_model_key(candidate.stem)
    name_key = frontend_model_key(candidate.name)
    if stem_key == target_key or name_key == target_key:
        return (0, len(candidate.parts))
    if target_key and target_key in stem_key:
        return (1, len(candidate.parts))
    if target_key and target_key in name_key:
        return (2, len(candidate.parts))
    return None


def _summarize_command_output(stdout: str, stderr: str) -> str:
    combined = "\n".join(part.strip() for part in (stderr, stdout) if part and part.strip())
    if not combined:
        return ""
    return combined.splitlines()[0].strip()[:400]
