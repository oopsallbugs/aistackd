"""llmfit-backed hardware detection and normalization helpers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LLMFIT_BINARY_NAME = "llmfit"
LLMFIT_SYSTEM_SUBCOMMAND = ("system", "--json")
CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION = "v1alpha1"


@dataclass(frozen=True)
class HardwareProfile:
    """Normalized hardware profile used for backend acquisition decisions."""

    schema_version: str
    detector: str
    backend: str
    acceleration_api: str
    target: str
    cmake_flags: tuple[str, ...]
    gpu_layers: int
    hsa_override_gfx_version: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "schema_version": self.schema_version,
            "detector": self.detector,
            "backend": self.backend,
            "acceleration_api": self.acceleration_api,
            "target": self.target,
            "cmake_flags": list(self.cmake_flags),
            "gpu_layers": self.gpu_layers,
            "hsa_override_gfx_version": self.hsa_override_gfx_version,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class LlmfitDetectionResult:
    """Result of invoking ``llmfit`` hardware detection."""

    detector: str
    available: bool
    ok: bool
    command: tuple[str, ...]
    exit_code: int | None
    raw_output: str
    raw_payload: dict[str, object] | None
    profile: HardwareProfile | None
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "detector": self.detector,
            "available": self.available,
            "ok": self.ok,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "raw_output": self.raw_output,
            "issues": list(self.issues),
        }
        if self.raw_payload is not None:
            payload["raw_payload"] = self.raw_payload
        if self.profile is not None:
            payload["profile"] = self.profile.to_dict()
        return payload


def detect_hardware_with_llmfit(llmfit_binary: str = LLMFIT_BINARY_NAME) -> LlmfitDetectionResult:
    """Run ``llmfit`` hardware detection and normalize the resulting profile."""
    resolved_binary = _resolve_executable(llmfit_binary)
    command = (resolved_binary or llmfit_binary, *LLMFIT_SYSTEM_SUBCOMMAND)
    if resolved_binary is None:
        return LlmfitDetectionResult(
            detector="llmfit",
            available=False,
            ok=False,
            command=command,
            exit_code=None,
            raw_output="",
            raw_payload=None,
            profile=None,
            issues=(f"'{llmfit_binary}' was not found on PATH",),
        )

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return LlmfitDetectionResult(
            detector="llmfit",
            available=True,
            ok=False,
            command=command,
            exit_code=None,
            raw_output="",
            raw_payload=None,
            profile=None,
            issues=(f"failed to run llmfit detection command: {exc}",),
        )

    raw_output = _combine_output(completed.stdout, completed.stderr)
    raw_payload = parse_json_first(raw_output)
    profile = hardware_profile_from_llmfit(raw_payload) if raw_payload is not None else None

    issues: list[str] = []
    if completed.returncode != 0:
        issues.append(f"llmfit exited with code {completed.returncode}")
    if raw_payload is None:
        issues.append("unable to parse llmfit JSON payload from command output")

    return LlmfitDetectionResult(
        detector="llmfit",
        available=True,
        ok=completed.returncode == 0 and profile is not None,
        command=command,
        exit_code=int(completed.returncode),
        raw_output=raw_output,
        raw_payload=raw_payload,
        profile=profile,
        issues=tuple(issues),
    )


def hardware_profile_from_llmfit(payload: dict[str, object]) -> HardwareProfile:
    """Convert llmfit system JSON into a deterministic hardware profile."""
    backend = _infer_backend(payload)
    target = _extract_gfx_target(payload)
    warnings: list[str] = []

    if backend == "nvidia":
        return HardwareProfile(
            schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
            detector="llmfit",
            backend="nvidia",
            acceleration_api="cuda",
            target="",
            cmake_flags=("-DGGML_CUDA=ON",),
            gpu_layers=99,
            hsa_override_gfx_version="",
        )

    if backend == "amd":
        flags = ["-DGGML_HIP=ON"]
        if target:
            flags.append(f"-DGPU_TARGETS={target}")
        else:
            warnings.append("AMD GPU detected but no gfx target found; using HIP defaults")
        hsa_override = "11.0.0"
        if target.startswith("gfx10"):
            hsa_override = "10.3.0"
        elif target.startswith("gfx9"):
            hsa_override = "9.0.6"
        return HardwareProfile(
            schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
            detector="llmfit",
            backend="amd",
            acceleration_api="rocm",
            target=target,
            cmake_flags=tuple(flags),
            gpu_layers=99,
            hsa_override_gfx_version=hsa_override,
            warnings=tuple(warnings),
        )

    if backend == "metal":
        return HardwareProfile(
            schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
            detector="llmfit",
            backend="metal",
            acceleration_api="metal",
            target="",
            cmake_flags=("-DGGML_METAL=ON",),
            gpu_layers=99,
            hsa_override_gfx_version="",
        )

    return HardwareProfile(
        schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
        detector="llmfit",
        backend="cpu",
        acceleration_api="cpu",
        target="",
        cmake_flags=(),
        gpu_layers=0,
        hsa_override_gfx_version="",
    )


def parse_json_first(payload_text: str) -> dict[str, object] | None:
    """Parse the first JSON object from text that may include log lines."""
    text = (payload_text or "").strip()
    if not text:
        return None

    try:
        loaded = json.loads(text)
    except ValueError:
        loaded = None
    if isinstance(loaded, dict):
        return loaded

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None

    try:
        loaded = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _resolve_executable(binary: str) -> str | None:
    path_candidate = Path(binary).expanduser()
    if path_candidate.anchor or "/" in binary:
        if path_candidate.exists():
            return str(path_candidate.resolve())
        return None
    return shutil.which(binary)


def _combine_output(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stdout, stderr) if part and part.strip()]
    return "\n".join(parts)


def _flatten_to_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for nested_value in value.values():
            yield from _flatten_to_strings(nested_value)
        return
    if isinstance(value, (list, tuple)):
        for nested_value in value:
            yield from _flatten_to_strings(nested_value)


def _extract_gfx_target(payload: dict[str, object]) -> str:
    for text in _flatten_to_strings(payload):
        match = re.search(r"(gfx[0-9]{4})", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


def _infer_backend(payload: dict[str, object]) -> str:
    explicit = payload.get("backend") or payload.get("provider")
    if isinstance(explicit, str) and explicit.strip():
        lowered = explicit.strip().lower()
        if any(token in lowered for token in ("cuda", "nvidia")):
            return "nvidia"
        if any(token in lowered for token in ("rocm", "hip", "amd")):
            return "amd"
        if "metal" in lowered:
            return "metal"
        if "cpu" in lowered:
            return "cpu"

    corpus = " ".join(text.lower() for text in _flatten_to_strings(payload))
    if "nvidia" in corpus or "cuda" in corpus:
        return "nvidia"
    if "rocm" in corpus or "hip" in corpus or "amd" in corpus:
        return "amd"
    if "metal" in corpus:
        return "metal"
    return "cpu"
