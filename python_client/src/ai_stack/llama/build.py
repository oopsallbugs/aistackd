"""llama.cpp clone and build helpers."""

from __future__ import annotations

import multiprocessing
import os
import shutil
import subprocess
from pathlib import Path


def clone_llama_cpp(config, force: bool = False) -> bool:
    """Clone llama.cpp repository into configured path."""
    if config.paths.llama_cpp_dir.exists():
        if force:
            shutil.rmtree(config.paths.llama_cpp_dir)
        else:
            print(f"✓ llama.cpp already exists at {config.paths.llama_cpp_dir}")
            return True

    print(f"Cloning llama.cpp to {config.paths.llama_cpp_dir}...")
    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/ggerganov/llama.cpp.git",
                str(config.paths.llama_cpp_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        print("✓ Cloned llama.cpp")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"✗ Failed to clone: {exc}")
        if exc.stderr:
            print(f"  Error: {exc.stderr.strip()}")
        return False


def build_llama_cpp(config) -> bool:
    """Build llama.cpp with configured GPU flags."""
    if config.is_llama_built:
        print("✓ llama.cpp already built")
        return True

    print(f"Building llama.cpp for {config.gpu.vendor.upper()}...")
    env = os.environ.copy()

    if config.gpu.vendor == "amd":
        try:
            result = subprocess.run(
                ["hipconfig", "-R"],
                capture_output=True,
                text=True,
                check=True,
            )
            rocm_root = result.stdout.strip()
            env["HIP_PATH"] = rocm_root
            env["ROCM_PATH"] = rocm_root

            hipcxx_candidates = [
                Path(rocm_root) / "bin" / "amdclang++",
                Path(rocm_root) / "bin" / "clang++",
            ]
            hipcxx_path = next((path for path in hipcxx_candidates if path.exists()), None)
            if hipcxx_path is not None:
                env["HIPCXX"] = str(hipcxx_path)

            if config.gpu.hsa_override_gfx_version:
                env["HSA_OVERRIDE_GFX_VERSION"] = config.gpu.hsa_override_gfx_version

        except Exception as exc:
            print(f"⚠ Warning: Could not set HIP environment: {exc}")

    build_dir = config.paths.llama_cpp_dir / "build"
    build_dir.mkdir(exist_ok=True)

    try:
        cmake_cmd = ["cmake", "..", "-DCMAKE_BUILD_TYPE=Release"]
        cmake_cmd.extend(config.gpu.cmake_flags)

        if config.gpu.vendor == "amd":
            rocm_root = Path(env.get("ROCM_PATH", "/opt/rocm"))
            amdclang = Path(env.get("HIP_PATH", "/opt/rocm")) / "bin" / "amdclang"
            hip_compiler_candidates = [
                rocm_root / "bin" / "amdclang++",
                rocm_root / "bin" / "clang++",
            ]
            hip_compiler = next((path for path in hip_compiler_candidates if path.exists()), None)
            cmake_cmd.extend(
                [
                    f"-DCMAKE_PREFIX_PATH={env.get('ROCM_PATH', '/opt/rocm')}",
                    f"-DCMAKE_HIP_COMPILER_ROCM_ROOT={rocm_root}",
                ]
            )
            if hip_compiler is not None:
                cmake_cmd.append(f"-DCMAKE_HIP_COMPILER={hip_compiler}")
            if amdclang.exists():
                cmake_cmd.append(f"-DCMAKE_C_COMPILER={amdclang}")
            if "HIPCXX" in env:
                cmake_cmd.append(f"-DCMAKE_CXX_COMPILER={env['HIPCXX']}")

        print(f"  Configuring with: {' '.join(cmake_cmd)}")

        subprocess.run(
            cmake_cmd,
            cwd=build_dir,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

        cores = multiprocessing.cpu_count()
        print(f"  Building with {cores} cores...")

        subprocess.run(
            ["cmake", "--build", ".", "--config", "Release", "-j", str(cores)],
            cwd=build_dir,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

        if config.llama_server_binary.exists():
            print("✓ Built llama.cpp successfully")
            return True

        print("✗ Build completed but llama-server not found")
        return False

    except subprocess.CalledProcessError as exc:
        print("✗ Build failed:")
        if exc.stdout:
            print(f"  Output: {exc.stdout.strip()[:500]}...")
        if exc.stderr:
            print(f"  Error: {exc.stderr.strip()[:500]}...")
        return False
