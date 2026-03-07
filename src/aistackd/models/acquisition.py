"""Managed model acquisition and GGUF adoption helpers."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from aistackd.models.llmfit import (
    LlmfitCommandError,
    extract_downloaded_gguf_path,
    run_llmfit_download,
)
from aistackd.models.selection import (
    derive_model_name_from_artifact_name,
    frontend_model_key,
    infer_quantization_from_artifact_name,
)
from aistackd.models.sources import (
    FALLBACK_MODEL_SOURCE,
    LLMFIT_BINARY_NAME,
    LOCAL_MODEL_SOURCE,
    PRIMARY_MODEL_SOURCE,
    SourceModel,
    local_source_model,
    model_source_order,
)
from aistackd.state.host import HostStatePaths, HostStateStore, InstalledModelRecord

DEFAULT_HUGGING_FACE_CLI = "hf"
GGUF_FILE_SUFFIX = ".gguf"
DEFAULT_LLMFIT_IMPORT_METHOD = "llmfit_watch_import"


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


@dataclass(frozen=True)
class HuggingFaceUrlReference:
    """Parsed Hugging Face repo/file reference."""

    repo: str
    filename: str | None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"repo": self.repo}
        if self.filename is not None:
            payload["filename"] = self.filename
        return payload


@dataclass(frozen=True)
class GgufSnapshotEntry:
    """Snapshot metadata for one GGUF candidate path."""

    path: str
    size_bytes: int
    modified_ns: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "modified_ns": self.modified_ns,
        }


@dataclass(frozen=True)
class ManagedGgufImportEntry:
    """Result of importing one GGUF candidate into managed state."""

    source_path: str
    model: str
    action: str
    detail: str
    artifact_path: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    acquisition_method: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_path": self.source_path,
            "model": self.model,
            "action": self.action,
            "detail": self.detail,
        }
        if self.artifact_path is not None:
            payload["artifact_path"] = self.artifact_path
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.sha256 is not None:
            payload["sha256"] = self.sha256
        if self.acquisition_method is not None:
            payload["acquisition_method"] = self.acquisition_method
        return payload


@dataclass(frozen=True)
class ManagedGgufImportReport:
    """Summary of importing one or more GGUF candidates."""

    entries: tuple[ManagedGgufImportEntry, ...]

    @property
    def imported_count(self) -> int:
        return sum(1 for entry in self.entries if entry.action == "imported")

    @property
    def skipped_count(self) -> int:
        return sum(1 for entry in self.entries if entry.action == "skipped")

    @property
    def failed_count(self) -> int:
        return sum(1 for entry in self.entries if entry.action == "failed")

    @property
    def imported(self) -> tuple[ManagedGgufImportEntry, ...]:
        return tuple(entry for entry in self.entries if entry.action == "imported")

    @property
    def skipped(self) -> tuple[ManagedGgufImportEntry, ...]:
        return tuple(entry for entry in self.entries if entry.action == "skipped")

    @property
    def failed(self) -> tuple[ManagedGgufImportEntry, ...]:
        return tuple(entry for entry in self.entries if entry.action == "failed")

    def to_dict(self) -> dict[str, object]:
        return {
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "entries": [entry.to_dict() for entry in self.entries],
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
    llmfit_binary: str = LLMFIT_BINARY_NAME,
    llmfit_quant: str | None = None,
    llmfit_budget_gb: float | None = None,
    llmfit_watch_roots: tuple[Path, ...] = (),
) -> ModelAcquisitionResult:
    """Acquire a managed model artifact using the configured policy order."""
    paths = HostStatePaths.from_project_root(project_root.resolve())
    attempts: list[ModelAcquisitionAttempt] = []
    if llmfit_quant is not None and not llmfit_quant.strip():
        raise ModelAcquisitionError("llmfit quantization must be a non-empty string when provided")
    if llmfit_budget_gb is not None and llmfit_budget_gb <= 0:
        raise ModelAcquisitionError("llmfit budget must be positive when provided")
    can_try_hugging_face = bool(hugging_face_repo and hugging_face_file)

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
            try:
                artifact_path, size_bytes, sha256, source_path = _acquire_from_llmfit(
                    paths,
                    source_model.name,
                    llmfit_binary=llmfit_binary,
                    quant=llmfit_quant,
                    budget_gb=llmfit_budget_gb,
                    watch_roots=llmfit_watch_roots,
                )
            except ModelAcquisitionError as exc:
                attempts.append(
                    ModelAcquisitionAttempt(
                        provider=PRIMARY_MODEL_SOURCE,
                        strategy="provider_download",
                        ok=False,
                        detail=str(exc),
                    )
                )
                if can_try_hugging_face:
                    continue
                raise ModelAcquisitionError(str(exc)) from exc

            attempts.append(
                ModelAcquisitionAttempt(
                    provider=PRIMARY_MODEL_SOURCE,
                    strategy="provider_download",
                    ok=True,
                    detail=f"downloaded GGUF with llmfit from '{source_path}'",
                    artifact_path=str(artifact_path),
                )
            )
            return ModelAcquisitionResult(
                source=PRIMARY_MODEL_SOURCE,
                acquisition_method="llmfit_download",
                artifact_path=str(artifact_path),
                size_bytes=size_bytes,
                sha256=sha256,
                attempts=tuple(attempts),
            )

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
        *(iter_llmfit_watch_roots()),
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


def iter_llmfit_watch_roots(extra_roots: tuple[Path, ...] = ()) -> tuple[Path, ...]:
    """Return the ordered set of llmfit watch roots used for import reconciliation."""
    home = Path.home()
    roots = (
        home / ".cache" / "llmfit",
        home / ".cache" / "huggingface" / "hub",
        *(path.expanduser().resolve() for path in extra_roots),
    )
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root.expanduser().resolve(strict=False))
    return tuple(deduped)


def snapshot_gguf_roots(watch_roots: tuple[Path, ...]) -> dict[str, GgufSnapshotEntry]:
    """Snapshot all GGUF files currently present under the watched roots."""
    snapshot: dict[str, GgufSnapshotEntry] = {}
    for root in watch_roots:
        if not root.exists() or not root.is_dir():
            continue
        for candidate in root.rglob(f"*{GGUF_FILE_SUFFIX}"):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            stat_result = resolved.stat()
            snapshot[str(resolved)] = GgufSnapshotEntry(
                path=str(resolved),
                size_bytes=int(stat_result.st_size),
                modified_ns=int(stat_result.st_mtime_ns),
            )
    return snapshot


def diff_gguf_snapshots(
    before: dict[str, GgufSnapshotEntry],
    after: dict[str, GgufSnapshotEntry],
) -> tuple[Path, ...]:
    """Return new or changed GGUF paths between two snapshots."""
    changed: list[Path] = []
    for path, entry in sorted(after.items()):
        previous = before.get(path)
        if previous is None or previous.size_bytes != entry.size_bytes or previous.modified_ns != entry.modified_ns:
            changed.append(Path(path))
    return tuple(changed)


def import_managed_gguf_candidates(
    project_root: Path,
    gguf_paths: tuple[Path, ...],
    *,
    source_name: str = PRIMARY_MODEL_SOURCE,
    acquisition_method: str = DEFAULT_LLMFIT_IMPORT_METHOD,
) -> ManagedGgufImportReport:
    """Import one or more GGUF paths into the managed host model store."""
    store = HostStateStore(project_root)
    paths = HostStatePaths.from_project_root(project_root.resolve())
    existing_records = {record.model: record for record in store.list_installed_models()}
    entries: list[ManagedGgufImportEntry] = []
    seen_candidates: set[str] = set()

    for candidate in sorted({path.expanduser().resolve() for path in gguf_paths}, key=str):
        source_path = str(candidate)
        if source_path in seen_candidates:
            continue
        seen_candidates.add(source_path)

        if not candidate.exists():
            entries.append(
                ManagedGgufImportEntry(
                    source_path=source_path,
                    model="",
                    action="failed",
                    detail=f"GGUF path '{candidate}' does not exist",
                )
            )
            continue
        if not candidate.is_file():
            entries.append(
                ManagedGgufImportEntry(
                    source_path=source_path,
                    model="",
                    action="failed",
                    detail=f"GGUF path '{candidate}' is not a file",
                )
            )
            continue
        if candidate.suffix.lower() != GGUF_FILE_SUFFIX:
            entries.append(
                ManagedGgufImportEntry(
                    source_path=source_path,
                    model="",
                    action="skipped",
                    detail=f"only '{GGUF_FILE_SUFFIX}' artifacts are eligible for managed import",
                )
            )
            continue

        sha256 = _file_sha256(candidate)
        size_bytes = candidate.stat().st_size
        base_model_name = derive_model_name_from_artifact_name(candidate.name)
        resolved_model_name = _resolve_import_model_name(base_model_name, sha256, existing_records)
        existing_record = existing_records.get(resolved_model_name)
        if existing_record is not None and existing_record.sha256 == sha256:
            entries.append(
                ManagedGgufImportEntry(
                    source_path=source_path,
                    model=resolved_model_name,
                    action="skipped",
                    detail="already installed with the same content hash",
                    artifact_path=existing_record.artifact_path,
                    size_bytes=existing_record.size_bytes,
                    sha256=existing_record.sha256,
                    acquisition_method=existing_record.acquisition_method,
                )
            )
            continue

        try:
            artifact_path, _, _ = _copy_local_gguf_into_managed_store(paths, resolved_model_name, candidate)
            record, _ = store.install_model(
                local_source_model(
                    resolved_model_name,
                    source=source_name,
                    summary=f"{source_name} GGUF import",
                    quantization=infer_quantization_from_artifact_name(candidate.name),
                    tags=(source_name, "import"),
                ),
                acquisition_source=source_name,
                acquisition_method=acquisition_method,
                artifact_path=artifact_path,
                size_bytes=size_bytes,
                sha256=sha256,
            )
        except ModelAcquisitionError as exc:
            entries.append(
                ManagedGgufImportEntry(
                    source_path=source_path,
                    model=resolved_model_name,
                    action="failed",
                    detail=str(exc),
                    sha256=sha256,
                )
            )
            continue

        existing_records[record.model] = record
        entries.append(
            ManagedGgufImportEntry(
                source_path=source_path,
                model=record.model,
                action="imported",
                detail="imported into managed host state",
                artifact_path=record.artifact_path,
                size_bytes=record.size_bytes,
                sha256=record.sha256,
                acquisition_method=record.acquisition_method,
            )
        )

    return ManagedGgufImportReport(entries=tuple(entries))


def parse_hugging_face_url(url: str) -> HuggingFaceUrlReference:
    """Parse a Hugging Face model URL into a repo and optional GGUF filename."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or parsed.netloc not in ("huggingface.co", "www.huggingface.co"):
        raise ModelAcquisitionError("Hugging Face URL must use the huggingface.co domain")

    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        raise ModelAcquisitionError("Hugging Face URL must include both owner and repo")

    repo = f"{path_parts[0]}/{path_parts[1]}"
    query = parse_qs(parsed.query)
    show_file_info = query.get("show_file_info")
    if show_file_info:
        filename = show_file_info[0].strip()
        return HuggingFaceUrlReference(repo=repo, filename=filename or None)

    if len(path_parts) >= 5 and path_parts[2] in ("resolve", "blob", "raw", "tree"):
        filename = "/".join(path_parts[4:]).strip()
        return HuggingFaceUrlReference(repo=repo, filename=filename or None)

    return HuggingFaceUrlReference(repo=repo, filename=None)


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


def _acquire_from_llmfit(
    paths: HostStatePaths,
    model_name: str,
    *,
    llmfit_binary: str,
    quant: str | None,
    budget_gb: float | None,
    watch_roots: tuple[Path, ...],
) -> tuple[Path, int, str, Path]:
    effective_watch_roots = iter_llmfit_watch_roots(watch_roots)
    before = snapshot_gguf_roots(effective_watch_roots)
    try:
        invocation = run_llmfit_download(
            model_name,
            llmfit_binary=llmfit_binary,
            quant=quant,
            budget_gb=budget_gb,
        )
    except LlmfitCommandError as exc:
        raise ModelAcquisitionError(str(exc)) from exc

    source_path = extract_downloaded_gguf_path(invocation.payload)
    if source_path is None:
        after = snapshot_gguf_roots(effective_watch_roots)
        changed_paths = diff_gguf_snapshots(before, after)
        if len(changed_paths) == 1:
            source_path = changed_paths[0]
        elif len(changed_paths) == 0:
            raise ModelAcquisitionError(
                "llmfit download did not identify a GGUF artifact; use models browse/import-llmfit, --gguf-path, or an explicit Hugging Face file install"
            )
        else:
            raise ModelAcquisitionError(
                "llmfit download produced multiple GGUF candidates; use models browse/import-llmfit, --gguf-path, or an explicit Hugging Face file install"
            )

    artifact_path, size_bytes, sha256 = _copy_local_gguf_into_managed_store(paths, model_name, source_path)
    return artifact_path, size_bytes, sha256, source_path


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


def _resolve_import_model_name(
    base_model_name: str,
    sha256: str,
    existing_records: dict[str, InstalledModelRecord],
) -> str:
    existing_record = existing_records.get(base_model_name)
    if existing_record is None or existing_record.sha256 == sha256:
        return base_model_name

    for length in (8, 12, 16, len(sha256)):
        candidate = f"{base_model_name}-{sha256[:length]}"
        candidate_record = existing_records.get(candidate)
        if candidate_record is None or candidate_record.sha256 == sha256:
            return candidate
    raise ModelAcquisitionError(f"unable to allocate a unique managed model id for '{base_model_name}'")


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
