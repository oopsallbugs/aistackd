"""Host prerequisite inspection, hardware detection, and acquisition planning."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from aistackd.runtime.backends import BackendDiscoveryResult, LlamaCppAcquisitionPlan, discover_llama_cpp_installation, plan_llama_cpp_acquisition
from aistackd.runtime.bootstrap import inspect_tool_status
from aistackd.runtime.hardware import LLMFIT_BINARY_NAME, LlmfitDetectionResult, detect_hardware_with_llmfit

MINIMUM_PYTHON_VERSION = (3, 11)
REQUIRED_HOST_COMMANDS = (
    ("node", "node"),
    ("cmake", "cmake"),
    ("make", "make"),
)
COMPILER_TOOLCHAIN_CANDIDATES = (
    ("gcc", "g++"),
    ("clang", "clang++"),
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
    """Combined prerequisite, hardware-detection, and backend-discovery report."""

    ok: bool
    prerequisite_checks: tuple[HostPrerequisiteCheck, ...]
    tool_checks: tuple[dict[str, object], ...]
    hardware_detection: LlmfitDetectionResult
    backend_discovery: BackendDiscoveryResult
    acquisition_plan: LlamaCppAcquisitionPlan | None = None

    @property
    def prerequisites_ok(self) -> bool:
        """Return whether all required prerequisite checks passed."""
        return all(check.ok or not check.required for check in self.prerequisite_checks)

    @property
    def hardware_detection_ok(self) -> bool:
        """Return whether llmfit hardware detection succeeded."""
        return self.hardware_detection.ok and self.hardware_detection.profile is not None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "ok": self.ok,
            "prerequisites_ok": self.prerequisites_ok,
            "hardware_detection_ok": self.hardware_detection_ok,
            "prerequisite_checks": [check.to_dict() for check in self.prerequisite_checks],
            "tool_checks": list(self.tool_checks),
            "hardware_detection": self.hardware_detection.to_dict(),
            "backend_discovery": self.backend_discovery.to_dict(),
        }
        if self.acquisition_plan is not None:
            payload["acquisition_plan"] = self.acquisition_plan.to_dict()
        return payload


def inspect_host_environment(
    *,
    project_root: Path | None = None,
    backend_root: Path | None = None,
    server_binary: Path | None = None,
    cli_binary: Path | None = None,
    llmfit_binary: str = LLMFIT_BINARY_NAME,
) -> HostInspectionReport:
    """Inspect host prerequisites, llmfit hardware detection, and backend discovery."""
    checks = (
        _python_check(),
        *_command_checks(),
        _compiler_toolchain_check(),
    )
    tool_project_root = project_root or Path.cwd()
    tool_checks = (
        inspect_tool_status(tool_project_root, "llmfit", requested=llmfit_binary).to_dict(),
        inspect_tool_status(tool_project_root, "hf").to_dict(),
    )
    hardware_detection = detect_hardware_with_llmfit(llmfit_binary)
    backend_discovery = discover_llama_cpp_installation(
        backend_root=backend_root,
        server_binary=server_binary,
        cli_binary=cli_binary,
    )
    acquisition_plan = (
        plan_llama_cpp_acquisition(hardware_detection.profile)
        if hardware_detection.profile is not None
        else None
    )
    ok = all(check.ok or not check.required for check in checks) and hardware_detection.ok
    return HostInspectionReport(
        ok=ok,
        prerequisite_checks=tuple(checks),
        tool_checks=tool_checks,
        hardware_detection=hardware_detection,
        backend_discovery=backend_discovery,
        acquisition_plan=acquisition_plan,
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


def _compiler_toolchain_check() -> HostPrerequisiteCheck:
    for cc_name, cxx_name in COMPILER_TOOLCHAIN_CANDIDATES:
        cc_path = shutil.which(cc_name)
        cxx_path = shutil.which(cxx_name)
        if cc_path is not None and cxx_path is not None:
            return HostPrerequisiteCheck(
                name="compiler_toolchain",
                required=False,
                ok=True,
                detail=f"using '{cc_name}' and '{cxx_name}'",
                path=f"{cc_path};{cxx_path}",
            )
    candidates = ", ".join(f"{cc}/{cxx}" for cc, cxx in COMPILER_TOOLCHAIN_CANDIDATES)
    return HostPrerequisiteCheck(
        name="compiler_toolchain",
        required=False,
        ok=False,
        detail=f"no supported compiler toolchain found on PATH ({candidates})",
        path=None,
    )
