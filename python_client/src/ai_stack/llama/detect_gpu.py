"""GPU detection utilities for ai_stack."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from typing import Any


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message)


def detect_linux_gpu(config: Any, verbose: bool = False, fallback_amd_target: str = "gfx1100") -> None:
    """Mutate a GPUConfig-like object based on Linux GPU detection."""
    try:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                config.vendor = "nvidia"
                config.layers = 99
                _log(verbose, f"  Detected NVIDIA GPU: {result.stdout.strip()}")
                return
        except (OSError, subprocess.SubprocessError):
            pass

        if os.path.exists("/dev/kfd"):
            config.vendor = "amd"
            config.layers = 99

            try:
                result = subprocess.run(
                    ["rocminfo"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    output = result.stdout
                    match = re.search(r"Name:\\s+(gfx[0-9]{4})", output)
                    if match:
                        config.target = match.group(1)
                        _log(verbose, f"  Detected AMD GPU via rocminfo: {config.target}")
                    else:
                        match = re.search(r"amdgcn-amd-amdhsa--(gfx[0-9]{4})", output)
                        if match:
                            config.target = match.group(1)
                            _log(verbose, f"  Detected AMD GPU via ISA: {config.target}")
                        else:
                            for line in output.split("\n"):
                                if "gfx" in line.lower():
                                    gfx_match = re.search(r"(gfx[0-9]{4})", line)
                                    if gfx_match:
                                        config.target = gfx_match.group(1)
                                        _log(verbose, f"  Detected AMD GPU via line match: {config.target}")
                                        break
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                _log(verbose, f"  rocminfo detection failed: {exc}")

            if not config.target:
                config.target = fallback_amd_target or "gfx1100"
                _log(verbose, f"  AMD target not auto-detected; defaulting to {config.target}")

            if config.target.startswith("gfx11"):
                config.hsa_override_gfx_version = "11.0.0"
            elif config.target.startswith("gfx10"):
                config.hsa_override_gfx_version = "10.3.0"
            elif config.target.startswith("gfx9"):
                config.hsa_override_gfx_version = "9.0.6"
            else:
                config.hsa_override_gfx_version = "11.0.0"

            _log(verbose, f"  HSA override: {config.hsa_override_gfx_version}")
            return

    except (OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError) as exc:
        _log(verbose, f"  GPU detection error: {exc}")

    if os.path.exists("/dev/kfd"):
        _log(verbose, "  /dev/kfd exists but detection failed, defaulting to AMD")
        config.vendor = "amd"
        config.target = fallback_amd_target or "gfx1100"
        config.hsa_override_gfx_version = "11.0.0"
        config.layers = 99
        return

    config.vendor = "cpu"
    config.layers = 0
    _log(verbose, "  No GPU detected, using CPU")


def detect_windows_gpu(config: Any, verbose: bool = False) -> None:
    """Placeholder Windows GPU detection."""
    config.vendor = "cpu"
    config.layers = 0
    _log(verbose, "  Windows GPU detection not implemented, using CPU")


def auto_detect_gpu(config: Any, verbose: bool = False, fallback_amd_target: str = "gfx1100") -> None:
    """Cross-platform auto-detection for a GPUConfig-like object."""
    system = platform.system()
    if system == "Linux":
        detect_linux_gpu(config=config, verbose=verbose, fallback_amd_target=fallback_amd_target)
    elif system == "Darwin":
        config.vendor = "metal"
        config.layers = 99
    elif system == "Windows":
        detect_windows_gpu(config=config, verbose=verbose)
