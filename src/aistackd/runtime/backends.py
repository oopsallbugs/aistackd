"""Backend discovery, acquisition planning, and adoption helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aistackd.models.sources import BACKEND_ACQUISITION_POLICY, PRIMARY_BACKEND
from aistackd.runtime.hardware import HardwareProfile
from aistackd.state.host import HostBackendInstallation

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


def adopt_backend_installation(discovery: BackendDiscoveryResult) -> HostBackendInstallation:
    """Convert a successful discovery result into persisted host state."""
    if not discovery.found or discovery.server_binary is None or discovery.backend_root is None:
        issues = "; ".join(discovery.issues) if discovery.issues else "backend installation was not found"
        raise ValueError(issues)

    return HostBackendInstallation(
        backend=discovery.backend,
        acquisition_method=f"adopted_{discovery.discovery_mode}",
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
