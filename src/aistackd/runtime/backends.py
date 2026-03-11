"""Backend discovery, acquisition planning, and managed acquisition helpers."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aistackd.models.sources import BACKEND_ACQUISITION_POLICY, PRIMARY_BACKEND
from aistackd.runtime.bootstrap import (
    LLAMA_CPP_BOOTSTRAP_MANIFEST,
    BootstrapError,
    download_url_to_path,
    extract_archive,
    resolve_llama_cpp_prebuilt_asset,
)
from aistackd.runtime.hardware import HardwareProfile
from aistackd.state.host import HostBackendInstallation, HostStatePaths

LLAMA_SERVER_BINARY_NAME = "llama-server"
LLAMA_CLI_BINARY_NAME = "llama-cli"


@dataclass(frozen=True)
class BackendDiscoveryResult:
    """Result of attempting to discover a backend installation."""

    backend: str
    found: bool
    discovery_mode: str
    backend_root: str | None
    server_binary: str | None
    cli_binary: str | None
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "backend": self.backend,
            "found": self.found,
            "discovery_mode": self.discovery_mode,
            "backend_root": self.backend_root,
            "server_binary": self.server_binary,
            "cli_binary": self.cli_binary,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class LlamaCppAcquisitionPlan:
    """Acquisition plan derived from a normalized hardware profile."""

    backend: str
    acquisition_policy: str
    flavor: str
    target: str
    primary_strategy: str
    fallback_strategy: str
    source_cmake_flags: tuple[str, ...]
    source_environment: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "backend": self.backend,
            "acquisition_policy": self.acquisition_policy,
            "flavor": self.flavor,
            "target": self.target,
            "primary_strategy": self.primary_strategy,
            "fallback_strategy": self.fallback_strategy,
            "source_cmake_flags": list(self.source_cmake_flags),
            "source_environment": {key: value for key, value in self.source_environment},
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class BackendAcquisitionAttempt:
    """One acquisition attempt and its outcome."""

    strategy: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "strategy": self.strategy,
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class BackendAcquisitionResult:
    """Result of acquiring or building a managed backend installation."""

    strategy: str
    installation: HostBackendInstallation
    attempts: tuple[BackendAcquisitionAttempt, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "strategy": self.strategy,
            "installation": self.installation.as_dict(),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "warnings": list(self.warnings),
        }


class BackendAcquisitionError(RuntimeError):
    """Raised when managed backend acquisition fails."""


def discover_llama_cpp_installation(
    *,
    backend_root: Path | None = None,
    server_binary: Path | None = None,
    cli_binary: Path | None = None,
) -> BackendDiscoveryResult:
    """Discover an existing ``llama.cpp`` installation without downloading anything."""
    issues: list[str] = []

    if server_binary is not None:
        normalized_server = server_binary.expanduser().resolve()
        if not normalized_server.exists():
            return BackendDiscoveryResult(
                backend=PRIMARY_BACKEND,
                found=False,
                discovery_mode="explicit_binary",
                backend_root=None,
                server_binary=str(normalized_server),
                cli_binary=str(cli_binary.expanduser().resolve()) if cli_binary is not None else None,
                issues=(f"server binary '{normalized_server}' does not exist",),
            )
        normalized_cli = cli_binary.expanduser().resolve() if cli_binary is not None else _paired_cli_binary(normalized_server)
        if normalized_cli is not None and not normalized_cli.exists():
            issues.append(f"cli binary '{normalized_cli}' does not exist")
            normalized_cli = None
        inferred_root = _infer_backend_root(normalized_server)
        return BackendDiscoveryResult(
            backend=PRIMARY_BACKEND,
            found=True,
            discovery_mode="explicit_binary",
            backend_root=str(inferred_root),
            server_binary=str(normalized_server),
            cli_binary=str(normalized_cli) if normalized_cli is not None else None,
            issues=tuple(issues),
        )

    if backend_root is not None:
        normalized_root = backend_root.expanduser().resolve()
        server_candidate = _find_backend_binary(normalized_root, LLAMA_SERVER_BINARY_NAME)
        cli_candidate = _find_backend_binary(normalized_root, LLAMA_CLI_BINARY_NAME)
        if server_candidate is None:
            return BackendDiscoveryResult(
                backend=PRIMARY_BACKEND,
                found=False,
                discovery_mode="explicit_root",
                backend_root=str(normalized_root),
                server_binary=None,
                cli_binary=str(cli_candidate) if cli_candidate is not None else None,
                issues=(f"no '{LLAMA_SERVER_BINARY_NAME}' binary found under '{normalized_root}'",),
            )
        if cli_candidate is None:
            issues.append(f"no '{LLAMA_CLI_BINARY_NAME}' binary found under '{normalized_root}'")
        return BackendDiscoveryResult(
            backend=PRIMARY_BACKEND,
            found=True,
            discovery_mode="explicit_root",
            backend_root=str(normalized_root),
            server_binary=str(server_candidate),
            cli_binary=str(cli_candidate) if cli_candidate is not None else None,
            issues=tuple(issues),
        )

    path_server = shutil.which(LLAMA_SERVER_BINARY_NAME)
    path_cli = shutil.which(LLAMA_CLI_BINARY_NAME)
    if path_server is None:
        return BackendDiscoveryResult(
            backend=PRIMARY_BACKEND,
            found=False,
            discovery_mode="path",
            backend_root=None,
            server_binary=None,
            cli_binary=path_cli,
            issues=(f"'{LLAMA_SERVER_BINARY_NAME}' was not found on PATH",),
        )

    normalized_server = Path(path_server).resolve()
    normalized_cli = Path(path_cli).resolve() if path_cli is not None else _paired_cli_binary(normalized_server)
    if normalized_cli is not None and not normalized_cli.exists():
        issues.append(f"paired cli binary '{normalized_cli}' does not exist")
        normalized_cli = None
    inferred_root = _infer_backend_root(normalized_server)
    return BackendDiscoveryResult(
        backend=PRIMARY_BACKEND,
        found=True,
        discovery_mode="path",
        backend_root=str(inferred_root),
        server_binary=str(normalized_server),
        cli_binary=str(normalized_cli) if normalized_cli is not None else None,
        issues=tuple(issues),
    )


def adopt_backend_installation(
    discovery: BackendDiscoveryResult,
    *,
    acquisition_method: str | None = None,
) -> HostBackendInstallation:
    """Convert a successful discovery result into persisted host state."""
    if not discovery.found or discovery.server_binary is None or discovery.backend_root is None:
        issues = "; ".join(discovery.issues) if discovery.issues else "backend installation was not found"
        raise ValueError(issues)

    return HostBackendInstallation(
        backend=discovery.backend,
        acquisition_method=acquisition_method or f"adopted_{discovery.discovery_mode}",
        backend_root=discovery.backend_root,
        server_binary=discovery.server_binary,
        cli_binary=discovery.cli_binary,
        configured_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def plan_llama_cpp_acquisition(hardware_profile: HardwareProfile) -> LlamaCppAcquisitionPlan:
    """Plan the preferred llama.cpp acquisition path for one hardware profile."""
    source_environment: list[tuple[str, str]] = []
    notes: list[str] = []

    if hardware_profile.acceleration_api == "cuda":
        notes.append("Prefer CUDA-enabled prebuilt llama.cpp artifacts for NVIDIA hosts.")
    elif hardware_profile.acceleration_api == "rocm":
        notes.append("Prefer ROCm-capable prebuilt artifacts when available; keep source fallback ready.")
        if hardware_profile.hsa_override_gfx_version:
            source_environment.append(("HSA_OVERRIDE_GFX_VERSION", hardware_profile.hsa_override_gfx_version))
    elif hardware_profile.acceleration_api == "metal":
        notes.append("Prefer Metal-enabled prebuilt artifacts for Apple hosts.")
    else:
        notes.append("No GPU accelerator detected; prefer CPU-oriented llama.cpp artifacts.")

    return LlamaCppAcquisitionPlan(
        backend=PRIMARY_BACKEND,
        acquisition_policy=BACKEND_ACQUISITION_POLICY,
        flavor=hardware_profile.acceleration_api,
        target=hardware_profile.target,
        primary_strategy="prebuilt",
        fallback_strategy="source",
        source_cmake_flags=hardware_profile.cmake_flags,
        source_environment=tuple(source_environment),
        warnings=hardware_profile.warnings,
        notes=tuple(notes),
    )


def acquire_managed_llama_cpp_installation(
    project_root: Path,
    plan: LlamaCppAcquisitionPlan,
    *,
    prebuilt_root: Path | None = None,
    prebuilt_archive: Path | None = None,
    source_root: Path | None = None,
    jobs: int | None = None,
) -> BackendAcquisitionResult:
    """Acquire a managed llama.cpp installation using the planned strategy order."""
    if prebuilt_root is not None and prebuilt_archive is not None:
        raise ValueError("provide only one prebuilt source: --prebuilt-root or --prebuilt-archive")

    paths = HostStatePaths.from_project_root(project_root.resolve())
    attempts: list[BackendAcquisitionAttempt] = []
    warnings = list(plan.warnings)

    if prebuilt_root is None and prebuilt_archive is None and source_root is None:
        remote_asset = resolve_llama_cpp_prebuilt_asset(plan.flavor)
        if remote_asset is not None:
            try:
                installation = _acquire_from_remote_prebuilt(paths, remote_asset)
            except BackendAcquisitionError as exc:
                attempts.append(BackendAcquisitionAttempt(strategy="downloaded_prebuilt", ok=False, detail=str(exc)))
            else:
                attempts.append(
                    BackendAcquisitionAttempt(strategy="downloaded_prebuilt", ok=True, detail="downloaded managed prebuilt")
                )
                return BackendAcquisitionResult(
                    strategy="downloaded_prebuilt",
                    installation=installation,
                    attempts=tuple(attempts),
                    warnings=tuple(warnings),
                )
        else:
            attempts.append(
                BackendAcquisitionAttempt(
                    strategy="downloaded_prebuilt",
                    ok=False,
                    detail=(
                        "no supported official prebuilt asset is pinned for "
                        f"{platform.system().lower()}/{platform.machine().lower()} flavor={plan.flavor}"
                    ),
                )
            )

        try:
            installation = _acquire_from_remote_source(paths, plan, jobs=jobs)
        except BackendAcquisitionError as exc:
            attempts.append(BackendAcquisitionAttempt(strategy="downloaded_source_build", ok=False, detail=str(exc)))
        else:
            attempts.append(
                BackendAcquisitionAttempt(strategy="downloaded_source_build", ok=True, detail="downloaded and built source fallback")
            )
            return BackendAcquisitionResult(
                strategy="downloaded_source_build",
                installation=installation,
                attempts=tuple(attempts),
                warnings=tuple(warnings),
            )

        detail = " ; ".join(f"{attempt.strategy}: {attempt.detail}" for attempt in attempts) or "no acquisition attempt was made"
        raise BackendAcquisitionError(detail)

    if prebuilt_root is not None:
        try:
            installation = _acquire_from_prebuilt_root(paths, prebuilt_root)
        except BackendAcquisitionError as exc:
            attempts.append(BackendAcquisitionAttempt(strategy="prebuilt_root", ok=False, detail=str(exc)))
        else:
            attempts.append(BackendAcquisitionAttempt(strategy="prebuilt_root", ok=True, detail="acquired managed prebuilt root"))
            return BackendAcquisitionResult(
                strategy="prebuilt_root",
                installation=installation,
                attempts=tuple(attempts),
                warnings=tuple(warnings),
            )

    if prebuilt_archive is not None:
        try:
            installation = _acquire_from_prebuilt_archive(paths, prebuilt_archive)
        except BackendAcquisitionError as exc:
            attempts.append(BackendAcquisitionAttempt(strategy="prebuilt_archive", ok=False, detail=str(exc)))
        else:
            attempts.append(
                BackendAcquisitionAttempt(strategy="prebuilt_archive", ok=True, detail="acquired managed prebuilt archive")
            )
            return BackendAcquisitionResult(
                strategy="prebuilt_archive",
                installation=installation,
                attempts=tuple(attempts),
                warnings=tuple(warnings),
            )

    if source_root is not None:
        try:
            installation = _acquire_from_source_build(paths, plan, source_root, jobs=jobs)
        except BackendAcquisitionError as exc:
            attempts.append(BackendAcquisitionAttempt(strategy="source_build", ok=False, detail=str(exc)))
        else:
            attempts.append(BackendAcquisitionAttempt(strategy="source_build", ok=True, detail="built managed source fallback"))
            return BackendAcquisitionResult(
                strategy="source_build",
                installation=installation,
                attempts=tuple(attempts),
                warnings=tuple(warnings),
            )

    detail = " ; ".join(f"{attempt.strategy}: {attempt.detail}" for attempt in attempts) or "no acquisition attempt was made"
    raise BackendAcquisitionError(detail)


def backend_installation_errors(installation: HostBackendInstallation | None) -> tuple[str, ...]:
    """Return validation errors for an adopted backend installation."""
    if installation is None:
        return ("no backend installation is configured for host runtime",)

    errors: list[str] = []
    backend_root = Path(installation.backend_root)
    server_binary = Path(installation.server_binary)
    if not backend_root.exists():
        errors.append(f"configured backend root '{backend_root}' does not exist")
    if not server_binary.exists():
        errors.append(f"configured backend server binary '{server_binary}' does not exist")
    if installation.cli_binary is not None and not Path(installation.cli_binary).exists():
        errors.append(f"configured backend cli binary '{installation.cli_binary}' does not exist")
    return tuple(errors)


def _find_backend_binary(root: Path, binary_name: str) -> Path | None:
    candidates = (
        root / "bin" / binary_name,
        root / binary_name,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _paired_cli_binary(server_binary: Path) -> Path | None:
    candidate = server_binary.with_name(LLAMA_CLI_BINARY_NAME)
    if candidate.exists():
        return candidate.resolve()
    return None


def _infer_backend_root(server_binary: Path) -> Path:
    if server_binary.parent.name == "bin":
        return server_binary.parent.parent.resolve()
    return server_binary.parent.resolve()


def _acquire_from_prebuilt_root(paths: HostStatePaths, prebuilt_root: Path) -> HostBackendInstallation:
    normalized_root = prebuilt_root.expanduser().resolve()
    if not normalized_root.exists():
        raise BackendAcquisitionError(f"prebuilt root '{normalized_root}' does not exist")
    if not normalized_root.is_dir():
        raise BackendAcquisitionError(f"prebuilt root '{normalized_root}' is not a directory")

    workspace_root = paths.backend_workspace_dir(PRIMARY_BACKEND)
    install_root = paths.backend_install_dir(PRIMARY_BACKEND)
    _reset_backend_workspace(workspace_root)
    shutil.copytree(normalized_root, install_root)

    discovery = discover_llama_cpp_installation(backend_root=install_root)
    if not discovery.found:
        issues = "; ".join(discovery.issues) if discovery.issues else "no llama-server binary was found after copying prebuilt root"
        raise BackendAcquisitionError(issues)
    return adopt_backend_installation(discovery, acquisition_method="acquired_prebuilt_root")


def _acquire_from_prebuilt_archive(paths: HostStatePaths, prebuilt_archive: Path) -> HostBackendInstallation:
    normalized_archive = prebuilt_archive.expanduser().resolve()
    if not normalized_archive.exists():
        raise BackendAcquisitionError(f"prebuilt archive '{normalized_archive}' does not exist")
    if not normalized_archive.is_file():
        raise BackendAcquisitionError(f"prebuilt archive '{normalized_archive}' is not a file")

    workspace_root = paths.backend_workspace_dir(PRIMARY_BACKEND)
    extract_root = paths.backend_extract_dir(PRIMARY_BACKEND)
    install_root = paths.backend_install_dir(PRIMARY_BACKEND)
    _reset_backend_workspace(workspace_root)
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        shutil.unpack_archive(str(normalized_archive), str(extract_root))
    except (shutil.ReadError, ValueError) as exc:
        raise BackendAcquisitionError(f"failed to unpack prebuilt archive '{normalized_archive}': {exc}") from exc

    candidate_root = _find_archive_backend_root(extract_root)
    if candidate_root is None:
        raise BackendAcquisitionError(f"no llama.cpp installation was found inside extracted archive '{normalized_archive}'")

    shutil.copytree(candidate_root, install_root)
    discovery = discover_llama_cpp_installation(backend_root=install_root)
    if not discovery.found:
        issues = "; ".join(discovery.issues) if discovery.issues else "no llama-server binary was found after unpacking prebuilt archive"
        raise BackendAcquisitionError(issues)
    return adopt_backend_installation(discovery, acquisition_method="acquired_prebuilt_archive")


def _acquire_from_source_build(
    paths: HostStatePaths,
    plan: LlamaCppAcquisitionPlan,
    source_root: Path,
    *,
    jobs: int | None = None,
) -> HostBackendInstallation:
    normalized_source = source_root.expanduser().resolve()
    if not normalized_source.exists():
        raise BackendAcquisitionError(f"source root '{normalized_source}' does not exist")
    if not normalized_source.is_dir():
        raise BackendAcquisitionError(f"source root '{normalized_source}' is not a directory")
    if not (normalized_source / "CMakeLists.txt").exists():
        raise BackendAcquisitionError(f"source root '{normalized_source}' does not contain a CMakeLists.txt file")
    _ensure_source_build_toolchain()

    workspace_root = paths.backend_workspace_dir(PRIMARY_BACKEND)
    source_copy_root = paths.backend_source_dir(PRIMARY_BACKEND)
    build_root = paths.backend_build_dir(PRIMARY_BACKEND)
    _reset_backend_workspace(workspace_root)
    shutil.copytree(
        normalized_source,
        source_copy_root,
        ignore=shutil.ignore_patterns(".git", "build", "__pycache__"),
    )

    command_environment = os.environ.copy()
    for key, value in plan.source_environment:
        command_environment[key] = value

    build_jobs = jobs if jobs is not None else max(1, os.cpu_count() or 1)
    if build_jobs < 1:
        raise BackendAcquisitionError("jobs must be a positive integer")

    configure_command = [
        "cmake",
        "-S",
        str(source_copy_root),
        "-B",
        str(build_root),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DLLAMA_BUILD_SERVER=ON",
        *plan.source_cmake_flags,
    ]
    build_command = [
        "cmake",
        "--build",
        str(build_root),
        "--config",
        "Release",
        "-j",
        str(build_jobs),
    ]
    _run_backend_command(configure_command, env=command_environment, phase="cmake configure")
    _run_backend_command(build_command, env=command_environment, phase="cmake build")

    discovery = discover_llama_cpp_installation(backend_root=build_root)
    if not discovery.found:
        issues = "; ".join(discovery.issues) if discovery.issues else "no llama-server binary was found after source build"
        raise BackendAcquisitionError(issues)
    return adopt_backend_installation(discovery, acquisition_method="acquired_source_build")


def _acquire_from_remote_prebuilt(paths: HostStatePaths, asset: LlamaCppPrebuiltAsset) -> HostBackendInstallation:
    workspace_root = paths.backend_workspace_dir(PRIMARY_BACKEND)
    extract_root = paths.backend_extract_dir(PRIMARY_BACKEND)
    _reset_backend_workspace(workspace_root)
    archive_name = Path(asset.url).name or "llama.cpp-prebuilt.zip"
    archive_path = workspace_root / archive_name
    try:
        checksum = download_url_to_path(asset.url, archive_path)
    except BootstrapError as exc:
        raise BackendAcquisitionError(str(exc)) from exc
    if asset.checksum is not None and checksum != asset.checksum:
        raise BackendAcquisitionError(
            f"downloaded prebuilt checksum mismatch for '{asset.url}': expected {asset.checksum}, got {checksum}"
        )
    try:
        extract_archive(archive_path, extract_root, archive_kind=asset.archive_kind)
    except BootstrapError as exc:
        raise BackendAcquisitionError(str(exc)) from exc

    candidate_root = _find_archive_backend_root(extract_root)
    if candidate_root is None:
        raise BackendAcquisitionError(f"downloaded prebuilt '{asset.url}' did not contain a llama.cpp installation")

    install_root = paths.backend_install_dir(PRIMARY_BACKEND)
    shutil.copytree(candidate_root, install_root)
    discovery = discover_llama_cpp_installation(backend_root=install_root)
    if not discovery.found:
        issues = "; ".join(discovery.issues) if discovery.issues else "no llama-server binary was found after downloading prebuilt"
        raise BackendAcquisitionError(issues)
    return adopt_backend_installation(discovery, acquisition_method="downloaded_prebuilt")


def _acquire_from_remote_source(
    paths: HostStatePaths,
    plan: LlamaCppAcquisitionPlan,
    *,
    jobs: int | None,
) -> HostBackendInstallation:
    workspace_root = paths.backend_workspace_dir(PRIMARY_BACKEND)
    _reset_backend_workspace(workspace_root)
    archive_path = workspace_root / f"llama.cpp-{LLAMA_CPP_BOOTSTRAP_MANIFEST.version}.tar.gz"
    try:
        checksum = download_url_to_path(LLAMA_CPP_BOOTSTRAP_MANIFEST.source_url, archive_path)
    except BootstrapError as exc:
        raise BackendAcquisitionError(str(exc)) from exc
    if (
        LLAMA_CPP_BOOTSTRAP_MANIFEST.source_checksum is not None
        and checksum != LLAMA_CPP_BOOTSTRAP_MANIFEST.source_checksum
    ):
        raise BackendAcquisitionError(
            "downloaded source checksum mismatch for "
            f"'{LLAMA_CPP_BOOTSTRAP_MANIFEST.source_url}': expected "
            f"{LLAMA_CPP_BOOTSTRAP_MANIFEST.source_checksum}, got {checksum}"
        )
    with tempfile.TemporaryDirectory(prefix="aistackd-llama-source-") as tmpdir:
        extract_root = Path(tmpdir) / "extract"
        try:
            extract_archive(archive_path, extract_root, archive_kind="tar.gz")
        except BootstrapError as exc:
            raise BackendAcquisitionError(str(exc)) from exc
        source_root = _find_source_tree_root(extract_root)
        if source_root is None:
            raise BackendAcquisitionError("downloaded llama.cpp source archive did not contain a buildable source tree")
        installation = _acquire_from_source_build(paths, plan, source_root, jobs=jobs)
    return HostBackendInstallation(
        backend=installation.backend,
        acquisition_method="downloaded_source_build",
        backend_root=installation.backend_root,
        server_binary=installation.server_binary,
        cli_binary=installation.cli_binary,
        configured_at=installation.configured_at,
    )


def _reset_backend_workspace(workspace_root: Path) -> None:
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)


def _find_archive_backend_root(extract_root: Path) -> Path | None:
    candidates = [extract_root, *(path for path in sorted(extract_root.rglob("*")) if path.is_dir())]
    for candidate in candidates:
        discovery = discover_llama_cpp_installation(backend_root=candidate)
        if discovery.found:
            return candidate
    return None


def _find_source_tree_root(extract_root: Path) -> Path | None:
    candidates = [extract_root, *(path for path in sorted(extract_root.rglob("*")) if path.is_dir())]
    for candidate in candidates:
        if (candidate / "CMakeLists.txt").exists():
            return candidate
    return None


def _ensure_source_build_toolchain() -> None:
    gcc = shutil.which("gcc")
    gxx = shutil.which("g++")
    clang = shutil.which("clang")
    clangxx = shutil.which("clang++")
    if (gcc is not None and gxx is not None) or (clang is not None and clangxx is not None):
        return
    raise BackendAcquisitionError("source fallback requires gcc/g++ or clang/clang++ on PATH")


def _run_backend_command(
    command: list[str],
    *,
    env: dict[str, str],
    phase: str,
) -> None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except OSError as exc:
        raise BackendAcquisitionError(f"{phase} command failed to start: {exc}") from exc
    if completed.returncode == 0:
        return
    output = _summarize_command_output(completed.stdout, completed.stderr)
    detail = f"{phase} failed with exit code {completed.returncode}"
    if output:
        detail += f": {output}"
    raise BackendAcquisitionError(detail)


def _summarize_command_output(stdout: str, stderr: str) -> str:
    combined = "\n".join(part.strip() for part in (stderr, stdout) if part and part.strip())
    if not combined:
        return ""
    first_line = combined.splitlines()[0].strip()
    return first_line[:400]
