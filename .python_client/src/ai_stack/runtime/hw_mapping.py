"""Map llmfit-detected hardware capability to llama.cpp build/runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class HardwareProfile:
    """Normalized hardware profile for bootstrap decisions."""

    backend: str
    target: str
    cmake_flags: tuple[str, ...]
    gpu_layers: int
    hsa_override_gfx_version: str
    warnings: tuple[str, ...] = ()


def _flatten_to_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _flatten_to_strings(nested)
        return
    if isinstance(value, list):
        for nested in value:
            yield from _flatten_to_strings(nested)


def _extract_gfx_target(payload: Dict[str, Any]) -> str:
    for text in _flatten_to_strings(payload):
        match = re.search(r"(gfx[0-9]{4})", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


def _infer_backend(payload: Dict[str, Any]) -> str:
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


def hardware_profile_from_llmfit(payload: Dict[str, Any]) -> HardwareProfile:
    """Convert llmfit system JSON into a deterministic build profile."""
    backend = _infer_backend(payload)
    target = _extract_gfx_target(payload)
    warnings: list[str] = []

    if backend == "nvidia":
        return HardwareProfile(
            backend="nvidia",
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
            backend="amd",
            target=target,
            cmake_flags=tuple(flags),
            gpu_layers=99,
            hsa_override_gfx_version=hsa_override,
            warnings=tuple(warnings),
        )
    if backend == "metal":
        return HardwareProfile(
            backend="metal",
            target="",
            cmake_flags=("-DGGML_METAL=ON",),
            gpu_layers=99,
            hsa_override_gfx_version="",
        )
    return HardwareProfile(
        backend="cpu",
        target="",
        cmake_flags=(),
        gpu_layers=0,
        hsa_override_gfx_version="",
    )


def validate_linux_privileges(profile: HardwareProfile) -> tuple[str, ...]:
    """Return warnings for likely Linux privilege/runtime capability issues."""
    warnings: list[str] = []
    if profile.backend == "nvidia":
        # nvidia-smi check is performed by caller to include stderr details.
        return ()
    if profile.backend == "amd":
        kfd = Path("/dev/kfd")
        if not kfd.exists():
            warnings.append("AMD backend selected but /dev/kfd was not found.")
        elif not kfd.stat().st_mode:
            warnings.append("AMD backend selected but /dev/kfd permissions look invalid.")
    return tuple(warnings)


def apply_profile_to_config(config: Any, profile: HardwareProfile) -> None:
    """
    Apply normalized hardware profile to a config-like object.

    Keeps this module independent from ai_stack.core.config classes.
    """
    config.gpu.vendor = profile.backend
    config.gpu.target = profile.target
    config.gpu.layers = profile.gpu_layers
    config.gpu.hsa_override_gfx_version = profile.hsa_override_gfx_version


def parse_json_first(payload_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse the first JSON object from text that may include extra log lines.

    llmfit can emit warnings before JSON payloads in some environments.
    """
    import json

    text = (payload_text or "").strip()
    if not text:
        return None
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else None
    except ValueError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        loaded = json.loads(text[start : end + 1])
        return loaded if isinstance(loaded, dict) else None
    except ValueError:
        return None


__all__ = [
    "HardwareProfile",
    "apply_profile_to_config",
    "hardware_profile_from_llmfit",
    "parse_json_first",
    "validate_linux_privileges",
]
