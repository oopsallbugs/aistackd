"""Host prerequisite inspection helpers."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from aistackd.runtime.backends import BackendDiscoveryResult, discover_llama_cpp_installation

MINIMUM_PYTHON_VERSION = (3, 11)
REQUIRED_HOST_COMMANDS = (
    ("node", "node"),
    ("cmake", "cmake"),
    ("make", "make"),
)


@dataclass(frozen=True)
class HostPrerequisiteCheck:
    """Result of one host prerequisite check."""

    name: str
    required: bool
    ok: bool
    detail: str
    path: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "name": self.name,
            "required": self.required,
            "ok": self.ok,
            "detail": self.detail,
            "path": self.path,
        }


@dataclass(frozen=True)
class HostInspectionReport:
    """Combined prerequisite and backend discovery report."""

    ok: bool
    prerequisite_checks: tuple[HostPrerequisiteCheck, ...]
    backend_discovery: BackendDiscoveryResult

    @property
    def prerequisites_ok(self) -> bool:
        """Return whether all required prerequisite checks passed."""
        return all(check.ok or not check.required for check in self.prerequisite_checks)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "ok": self.ok,
            "prerequisites_ok": self.prerequisites_ok,
            "prerequisite_checks": [check.to_dict() for check in self.prerequisite_checks],
            "backend_discovery": self.backend_discovery.to_dict(),
        }


def inspect_host_environment(
    *,
    backend_root: Path | None = None,
    server_binary: Path | None = None,
    cli_binary: Path | None = None,
) -> HostInspectionReport:
    """Inspect host prerequisites plus backend discovery readiness."""
    checks = (
        _python_check(),
        *_command_checks(),
    )
    backend_discovery = discover_llama_cpp_installation(
        backend_root=backend_root,
        server_binary=server_binary,
        cli_binary=cli_binary,
    )
    ok = all(check.ok or not check.required for check in checks) and backend_discovery.found
    return HostInspectionReport(
        ok=ok,
        prerequisite_checks=tuple(checks),
        backend_discovery=backend_discovery,
    )


def _python_check() -> HostPrerequisiteCheck:
    current_version = sys.version_info[:3]
    ok = current_version >= MINIMUM_PYTHON_VERSION
    detail = f"python {current_version[0]}.{current_version[1]}.{current_version[2]}"
    if not ok:
        detail += (
            f" is below the required minimum "
            f"{MINIMUM_PYTHON_VERSION[0]}.{MINIMUM_PYTHON_VERSION[1]}"
        )
    return HostPrerequisiteCheck(
        name="python",
        required=True,
        ok=ok,
        detail=detail,
        path=str(Path(sys.executable).resolve()),
    )


def _command_checks() -> tuple[HostPrerequisiteCheck, ...]:
    checks: list[HostPrerequisiteCheck] = []
    for label, command_name in REQUIRED_HOST_COMMANDS:
        resolved = shutil.which(command_name)
        checks.append(
            HostPrerequisiteCheck(
                name=label,
                required=True,
                ok=resolved is not None,
                detail=(f"'{command_name}' is available" if resolved is not None else f"'{command_name}' is missing from PATH"),
                path=resolved,
            )
        )
    return tuple(checks)

