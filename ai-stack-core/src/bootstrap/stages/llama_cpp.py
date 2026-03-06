"""llama.cpp sync and build stages."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any

from bootstrap.contracts import STAGE_HW_MAP
from bootstrap.errors import StageError
from bootstrap.runner import StageContext
from bootstrap.stages.common import run_checked, runtime_root

LLAMA_CPP_REPO_URL = "https://github.com/ggerganov/llama.cpp.git"


def normalize_cmake_flags_for_build(ctx: StageContext, cmake_flags: list[str]) -> list[str]:
    _ = ctx
    return list(cmake_flags)


def is_git_dirty_checkout_error(message: str) -> bool:
    lowered = (message or "").lower()
    patterns = (
        "would be overwritten by checkout",
        "please commit your changes",
        "your local changes",
        "local changes to the following files",
    )
    return any(pattern in lowered for pattern in patterns)


def forced_cpu_flags(cmake_flags: list[str]) -> list[str]:
    flags = [
        flag
        for flag in cmake_flags
        if flag
        not in {
            "-DGGML_HIP=ON",
            "-DGGML_CUDA=ON",
            "-DGGML_HIP=OFF",
            "-DGGML_CUDA=OFF",
        }
    ]
    flags.extend(["-DGGML_HIP=OFF", "-DGGML_CUDA=OFF"])
    return flags


def is_hip_wavefront_compat_failure(message: str) -> bool:
    return "__amdgcn_wavefront_size" in (message or "").lower()


def llama_build_hints(errors: list[str]) -> list[str]:
    joined = " | ".join(errors)
    hints: list[str] = []
    if is_hip_wavefront_compat_failure(joined):
        hints.append(
            "HIP compile failed on '__AMDGCN_WAVEFRONT_SIZE'; this usually means a ROCm/clang <-> llama.cpp compatibility mismatch. "
            "Update ROCm, or pin llama.cpp to a compatible commit for your toolchain/GPU target."
        )
    return hints


def stage_llama_sync(ctx: StageContext) -> dict[str, Any]:
    llama_dir = runtime_root(ctx.project_root) / "llama.cpp"
    ref = str(ctx.options.llama_cpp_commit).strip()
    if not ref:
        raise StageError(code="llama_sync_failed", message="llama.cpp ref is empty", retryable=False)

    if llama_dir.exists() and not (llama_dir / ".git").exists():
        raise StageError(
            code="llama_sync_failed",
            message="llama.cpp directory exists but is not a git repository",
            retryable=True,
        )

    try:
        if not (llama_dir / ".git").exists():
            llama_dir.parent.mkdir(parents=True, exist_ok=True)
            run_checked(["git", "clone", LLAMA_CPP_REPO_URL, str(llama_dir)], timeout_seconds=1800)
        else:
            run_checked(["git", "-C", str(llama_dir), "fetch", "--all", "--tags", "--prune"], timeout_seconds=1800)

        run_checked(["git", "-C", str(llama_dir), "fetch", "origin", ref], timeout_seconds=1800)
        run_checked(["git", "-C", str(llama_dir), "checkout", ref], timeout_seconds=300)
        run_checked(["git", "-C", str(llama_dir), "submodule", "update", "--init", "--recursive"], timeout_seconds=1800)
        resolved_commit = run_checked(["git", "-C", str(llama_dir), "rev-parse", "HEAD"], timeout_seconds=30).stdout.strip()
    except Exception as exc:
        message = f"Failed to sync llama.cpp: {exc}"
        if is_git_dirty_checkout_error(str(exc)):
            message += (
                "\nDetected local changes in .ai_stack/llama.cpp that block git checkout."
                "\nRemediation:"
                "\n- Remove and re-clone runtime checkout: rm -rf .ai_stack/llama.cpp"
                "\n- Or clean/commit local changes in .ai_stack/llama.cpp, then rerun bootstrap."
            )
        raise StageError(code="llama_sync_failed", message=message, retryable=True) from exc

    return {
        "resolved_commit": resolved_commit,
        "artifacts": {
            "llama_cpp_dir": str(llama_dir),
            "llama_cpp_commit": resolved_commit,
        },
    }


def stage_llama_build(ctx: StageContext) -> dict[str, Any]:
    llama_dir_value = ctx.checkpoint.get("artifacts", {}).get("llama_cpp_dir")
    if not llama_dir_value:
        raise StageError(code="llama_build_failed", message="llama_cpp_dir artifact is missing", retryable=True)

    llama_dir = Path(str(llama_dir_value))
    if not llama_dir.exists():
        raise StageError(code="llama_build_failed", message=f"llama.cpp directory not found: {llama_dir}", retryable=True)

    build_dir = llama_dir / "build"
    hw_map_output = ctx.checkpoint["stages"][STAGE_HW_MAP].get("output", {})
    hw_backend = str(hw_map_output.get("backend", "")).lower()
    hw_accel = str(hw_map_output.get("acceleration_api", "")).lower()
    if hw_backend == "amd" and hw_accel != "rocm":
        raise StageError(code="unsupported_hw_profile", message="Unsupported AMD acceleration profile")

    cmake_flags = [str(flag) for flag in hw_map_output.get("cmake_flags", []) if isinstance(flag, str)]
    cmake_flags = normalize_cmake_flags_for_build(ctx, cmake_flags)
    attempt_flag_sets: list[tuple[str, list[str]]] = [("primary", cmake_flags)]
    if hw_backend == "amd" and "-DGGML_HIP=ON" in cmake_flags and bool(ctx.options.allow_cpu_fallback):
        attempt_flag_sets.append(("fallback_cpu", forced_cpu_flags(cmake_flags)))

    jobs = max(1, os.cpu_count() or 1)
    errors: list[str] = []
    built_server: Path | None = None

    for attempt_name, attempt_flags in attempt_flag_sets:
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        configure_cmd = [
            "cmake",
            "-S",
            str(llama_dir),
            "-B",
            str(build_dir),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DLLAMA_BUILD_SERVER=ON",
            *attempt_flags,
        ]
        build_cmd = ["cmake", "--build", str(build_dir), "--config", "Release", "-j", str(jobs)]

        try:
            run_checked(configure_cmd, timeout_seconds=1800)
            run_checked(build_cmd, timeout_seconds=7200)
            candidates = [
                build_dir / "bin" / "llama-server",
                build_dir / "bin" / "llama-server.exe",
            ]
            built_server = next((candidate for candidate in candidates if candidate.exists()), None)
            if built_server is None:
                raise RuntimeError("Build completed but llama-server binary was not found under build/bin")
            if attempt_name != "primary":
                print(f"[bootstrap.llama.build] recovered using fallback configure flags ({attempt_name})")
            break
        except Exception as exc:
            errors.append(f"{attempt_name}: {exc}")

    if built_server is None:
        message = "Failed to build llama.cpp: " + " | ".join(errors)
        hints = llama_build_hints(errors)
        if hints:
            message += "\nHints:\n- " + "\n- ".join(hints)
        raise StageError(code="llama_build_failed", message=message, retryable=True)

    return {
        "binary": str(built_server),
        "artifacts": {
            "llama_server_binary": str(built_server),
        },
    }


__all__ = [
    "forced_cpu_flags",
    "is_git_dirty_checkout_error",
    "llama_build_hints",
    "normalize_cmake_flags_for_build",
    "run_checked",
    "stage_llama_build",
    "stage_llama_sync",
]
