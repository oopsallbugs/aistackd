"""Clean-host bootstrap helpers for operator tools and managed backend assets."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib import request

from aistackd.state.host import HostStateStore, InstalledToolRecord

DEFAULT_USER_BIN_DIR: Final[Path] = Path.home() / ".local" / "bin"
DEFAULT_TOOL_SUPPORT_ROOT: Final[Path] = Path.home() / ".local" / "share" / "aistackd" / "tools"
LLAMA_CPP_BOOTSTRAP_VERSION: Final[str] = "b7472"


class BootstrapError(RuntimeError):
    """Raised when clean-host bootstrap cannot complete."""


@dataclass(frozen=True)
class BootstrapToolSpec:
    """Pinned install metadata for one operator tool."""

    name: str
    installer_url: str
    installer_args: tuple[str, ...]
    version_command: tuple[str, ...]
    checksum: str | None = None
    install_method: str = "installer_script"
    persistent_home: bool = False


@dataclass(frozen=True)
class BootstrapToolStatus:
    """Observed availability for one operator tool."""

    tool: str
    ok: bool
    source: str
    executable_path: str | None
    version: str | None
    status: str
    install_method: str | None = None
    source_url: str | None = None
    checksum: str | None = None
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "tool": self.tool,
            "ok": self.ok,
            "source": self.source,
            "status": self.status,
            "issues": list(self.issues),
        }
        if self.executable_path is not None:
            payload["executable_path"] = self.executable_path
        if self.version is not None:
            payload["version"] = self.version
        if self.install_method is not None:
            payload["install_method"] = self.install_method
        if self.source_url is not None:
            payload["source_url"] = self.source_url
        if self.checksum is not None:
            payload["checksum"] = self.checksum
        return payload


@dataclass(frozen=True)
class BootstrapToolInstallResult:
    """Result of installing one operator tool."""

    action: str
    record: InstalledToolRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "tool": self.record.as_dict(),
        }


@dataclass(frozen=True)
class LlamaCppPrebuiltAsset:
    """One pinned prebuilt asset candidate."""

    os_name: str
    arch: str
    flavor: str
    url: str
    archive_kind: str
    checksum: str | None = None


@dataclass(frozen=True)
class LlamaCppBootstrapManifest:
    """Pinned bootstrap manifest for remote llama.cpp acquisition."""

    version: str
    source_url: str
    source_checksum: str | None
    prebuilt_assets: tuple[LlamaCppPrebuiltAsset, ...]


BOOTSTRAP_TOOL_SPECS: Final[dict[str, BootstrapToolSpec]] = {
    "llmfit": BootstrapToolSpec(
        name="llmfit",
        installer_url="https://llmfit.axjns.dev/install.sh",
        installer_args=("--local",),
        version_command=("--version",),
    ),
    "hf": BootstrapToolSpec(
        name="hf",
        installer_url="https://hf.co/cli/install.sh",
        installer_args=(),
        version_command=("version",),
        persistent_home=True,
    ),
}

LLAMA_CPP_BOOTSTRAP_MANIFEST: Final[LlamaCppBootstrapManifest] = LlamaCppBootstrapManifest(
    version=LLAMA_CPP_BOOTSTRAP_VERSION,
    source_url=f"https://github.com/ggml-org/llama.cpp/archive/refs/tags/{LLAMA_CPP_BOOTSTRAP_VERSION}.tar.gz",
    source_checksum=None,
    prebuilt_assets=(
        LlamaCppPrebuiltAsset(
            os_name="linux",
            arch="x86_64",
            flavor="cpu",
            url=(
                "https://github.com/ggml-org/llama.cpp/releases/download/"
                f"{LLAMA_CPP_BOOTSTRAP_VERSION}/llama-{LLAMA_CPP_BOOTSTRAP_VERSION}-bin-ubuntu-x64.zip"
            ),
            archive_kind="zip",
        ),
    ),
)


def resolve_tool_binary(
    project_root: Path,
    tool_name: str,
    *,
    requested: str,
) -> str:
    """Resolve one tool binary from explicit args, persisted state, or PATH."""
    if requested and requested != tool_name:
        return _resolve_explicit_binary(requested)

    store = HostStateStore(project_root)
    installed_record = store.load_installed_tool(tool_name)
    if installed_record is not None and Path(installed_record.executable_path).exists():
        return str(Path(installed_record.executable_path).resolve())

    return _resolve_explicit_binary(requested or tool_name)


def inspect_tool_status(
    project_root: Path,
    tool_name: str,
    *,
    requested: str | None = None,
) -> BootstrapToolStatus:
    """Return the current availability of one operator tool."""
    requested_binary = requested or tool_name
    explicit_override = requested is not None and requested != tool_name
    store = HostStateStore(project_root)
    installed_record = store.load_installed_tool(tool_name)

    if explicit_override:
        try:
            resolved = _resolve_explicit_binary(requested_binary)
        except BootstrapError as exc:
            return BootstrapToolStatus(
                tool=tool_name,
                ok=False,
                source="explicit",
                executable_path=None,
                version=None,
                status="missing",
                issues=(str(exc),),
            )
        return BootstrapToolStatus(
            tool=tool_name,
            ok=True,
            source="explicit",
            executable_path=resolved,
            version=_probe_tool_version(resolved, BOOTSTRAP_TOOL_SPECS[tool_name].version_command),
            status="available",
        )

    if installed_record is not None:
        if Path(installed_record.executable_path).exists():
            return BootstrapToolStatus(
                tool=tool_name,
                ok=True,
                source="managed",
                executable_path=installed_record.executable_path,
                version=installed_record.version,
                status=installed_record.status,
                install_method=installed_record.install_method,
                source_url=installed_record.source_url,
                checksum=installed_record.checksum,
            )
        return BootstrapToolStatus(
            tool=tool_name,
            ok=False,
            source="managed",
            executable_path=installed_record.executable_path,
            version=installed_record.version,
            status="missing_binary",
            install_method=installed_record.install_method,
            source_url=installed_record.source_url,
            checksum=installed_record.checksum,
            issues=(f"managed tool '{installed_record.executable_path}' does not exist",),
        )

    resolved = shutil.which(tool_name)
    if resolved is not None:
        return BootstrapToolStatus(
            tool=tool_name,
            ok=True,
            source="path",
            executable_path=str(Path(resolved).resolve()),
            version=_probe_tool_version(resolved, BOOTSTRAP_TOOL_SPECS[tool_name].version_command),
            status="available",
        )

    return BootstrapToolStatus(
        tool=tool_name,
        ok=False,
        source="missing",
        executable_path=None,
        version=None,
        status="missing",
        issues=(f"'{tool_name}' was not found on PATH or in managed host state",),
    )


def install_tool(
    project_root: Path,
    tool_name: str,
    *,
    user_bin_dir: Path = DEFAULT_USER_BIN_DIR,
) -> BootstrapToolInstallResult:
    """Install one operator tool into a normal user bin directory."""
    try:
        spec = BOOTSTRAP_TOOL_SPECS[tool_name]
    except KeyError as exc:
        raise BootstrapError(f"unknown bootstrap tool '{tool_name}'") from exc

    final_bin_dir = user_bin_dir.expanduser().resolve()
    final_bin_dir.mkdir(parents=True, exist_ok=True)
    installer_checksum = ""
    if spec.persistent_home:
        script_path = final_bin_dir / f".{tool_name}-install.sh"
        support_home = _tool_support_home(tool_name)
        try:
            installer_checksum = download_url_to_path(spec.installer_url, script_path)
            if spec.checksum is not None and installer_checksum != spec.checksum:
                raise BootstrapError(
                    f"{tool_name} installer checksum mismatch: expected {spec.checksum}, got {installer_checksum}"
                )
            shutil.rmtree(support_home, ignore_errors=True)
            support_home.mkdir(parents=True, exist_ok=True)
            staged_bin_dir = support_home / ".local" / "bin"
            _run_installer_script(script_path, spec, support_home)
            staged_binary = staged_bin_dir / tool_name
            if not staged_binary.exists():
                raise BootstrapError(f"{tool_name} installer did not produce '{staged_binary}'")
            final_binary = final_bin_dir / tool_name
            _copy_file_atomic(staged_binary, final_binary)
            final_binary.chmod(0o755)
        finally:
            script_path.unlink(missing_ok=True)
    else:
        with tempfile.TemporaryDirectory(prefix=f"aistackd-{tool_name}-") as tmpdir:
            temp_root = Path(tmpdir)
            script_path = temp_root / f"{tool_name}-install.sh"
            installer_checksum = download_url_to_path(spec.installer_url, script_path)
            if spec.checksum is not None and installer_checksum != spec.checksum:
                raise BootstrapError(
                    f"{tool_name} installer checksum mismatch: expected {spec.checksum}, got {installer_checksum}"
                )

            staged_home = temp_root / "home"
            staged_home.mkdir(parents=True, exist_ok=True)
            staged_bin_dir = staged_home / ".local" / "bin"
            _run_installer_script(script_path, spec, staged_home)

            staged_binary = staged_bin_dir / tool_name
            if not staged_binary.exists():
                raise BootstrapError(f"{tool_name} installer did not produce '{staged_binary}'")

            final_binary = final_bin_dir / tool_name
            _copy_file_atomic(staged_binary, final_binary)
            final_binary.chmod(0o755)

    version = _probe_tool_version(str(final_binary), spec.version_command)
    record = InstalledToolRecord(
        tool=tool_name,
        executable_path=str(final_binary),
        version=version,
        source_url=spec.installer_url,
        checksum=installer_checksum,
        installed_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        install_method=spec.install_method,
    )

    store = HostStateStore(project_root)
    created = store.save_installed_tool(record)
    return BootstrapToolInstallResult(action="installed" if created else "updated", record=record)


def resolve_llama_cpp_prebuilt_asset(
    flavor: str,
    *,
    os_name: str | None = None,
    arch: str | None = None,
) -> LlamaCppPrebuiltAsset | None:
    """Resolve one pinned prebuilt asset for the current platform."""
    effective_os = os_name or _normalize_os_name()
    effective_arch = arch or _normalize_arch_name()
    for asset in LLAMA_CPP_BOOTSTRAP_MANIFEST.prebuilt_assets:
        if asset.os_name == effective_os and asset.arch == effective_arch and asset.flavor == flavor:
            return asset
    return None


def download_url_to_path(url: str, destination: Path) -> str:
    """Download one URL to disk and return the file sha256."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        with request.urlopen(url) as response, destination.open("wb") as handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise BootstrapError(f"failed to download '{url}': {exc}") from exc
    return digest.hexdigest()


def extract_archive(archive_path: Path, destination: Path, *, archive_kind: str) -> None:
    """Extract one downloaded archive into a destination directory."""
    destination.mkdir(parents=True, exist_ok=True)
    if archive_kind == "zip":
        with zipfile.ZipFile(archive_path) as handle:
            handle.extractall(destination)
        return
    if archive_kind in {"tar.gz", "tgz"}:
        with tarfile.open(archive_path, "r:gz") as handle:
            handle.extractall(destination)
        return
    raise BootstrapError(f"unsupported archive kind '{archive_kind}'")


def normalize_user_bin_dir(path: Path | None) -> Path:
    """Return the normalized user-bin install directory."""
    return (path or DEFAULT_USER_BIN_DIR).expanduser().resolve()


def _tool_support_home(tool_name: str) -> Path:
    return (DEFAULT_TOOL_SUPPORT_ROOT / tool_name / "home").expanduser().resolve()


def _resolve_explicit_binary(binary_name: str) -> str:
    candidate = Path(binary_name).expanduser()
    if candidate.anchor or "/" in binary_name:
        if candidate.exists():
            return str(candidate.resolve())
        raise BootstrapError(f"'{binary_name}' does not exist")
    resolved = shutil.which(binary_name)
    if resolved is not None:
        return str(Path(resolved).resolve())
    raise BootstrapError(f"'{binary_name}' was not found on PATH")


def _run_installer_script(script_path: Path, spec: BootstrapToolSpec, staged_home: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(staged_home)
    command = ["sh", str(script_path), *spec.installer_args]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    except OSError as exc:
        raise BootstrapError(f"failed to launch {spec.name} installer: {exc}") from exc
    if completed.returncode == 0:
        return
    detail = _summarize_command_output(completed.stdout, completed.stderr)
    message = f"{spec.name} installer exited with code {completed.returncode}"
    if detail:
        message += f": {detail}"
    raise BootstrapError(message)


def _probe_tool_version(binary_path: str, version_command: tuple[str, ...]) -> str:
    command = [binary_path, *version_command]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError:
        return "unknown"
    if completed.returncode != 0:
        fallback = (completed.stdout or completed.stderr).strip()
        return fallback.splitlines()[0].strip() if fallback else "unknown"
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0].strip() if output else "unknown"


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(destination.parent), delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        shutil.copy2(source, temp_path)
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)


def _normalize_os_name() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "windows"
    return system


def _normalize_arch_name() -> str:
    machine = platform.machine().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "arm64": "aarch64",
    }
    return aliases.get(machine, machine)


def _summarize_command_output(stdout: str, stderr: str) -> str:
    combined = "\n".join(part.strip() for part in (stderr, stdout) if part and part.strip())
    if not combined:
        return ""
    first_line = combined.splitlines()[0].strip()
    return first_line[:240]
