"""Bootstrap installer and remote backend acquisition tests."""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from aistackd.runtime.backends import acquire_managed_llama_cpp_installation, plan_llama_cpp_acquisition
from aistackd.runtime.bootstrap import BootstrapToolSpec, install_tool, resolve_tool_binary
from aistackd.runtime.hardware import CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION, HardwareProfile


class BootstrapToolTests(unittest.TestCase):
    def test_install_tool_writes_binary_to_selected_user_bin_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            user_bin_dir = Path(tmpdir) / "user-bin"

            with (
                patch(
                    "aistackd.runtime.bootstrap.download_url_to_path",
                    side_effect=_fake_tool_download,
                ),
                patch(
                    "aistackd.runtime.bootstrap._run_installer_script",
                    side_effect=_fake_tool_installer_run,
                ),
                patch(
                    "aistackd.runtime.bootstrap._probe_tool_version",
                    return_value="llmfit 0.6.2",
                ),
            ):
                result = install_tool(project_root, "llmfit", user_bin_dir=user_bin_dir)

            self.assertEqual(result.action, "installed")
            self.assertEqual(result.record.tool, "llmfit")
            self.assertTrue((user_bin_dir / "llmfit").exists())
            self.assertEqual(resolve_tool_binary(project_root, "llmfit", requested="llmfit"), str((user_bin_dir / "llmfit").resolve()))

    def test_install_hf_uses_persistent_support_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            user_bin_dir = Path(tmpdir) / "user-bin"
            support_root = Path(tmpdir) / "tool-support"

            with (
                patch("aistackd.runtime.bootstrap.DEFAULT_TOOL_SUPPORT_ROOT", support_root),
                patch(
                    "aistackd.runtime.bootstrap.download_url_to_path",
                    side_effect=_fake_tool_download,
                ),
                patch(
                    "aistackd.runtime.bootstrap._run_installer_script",
                    side_effect=_fake_hf_installer_run,
                ),
                patch(
                    "aistackd.runtime.bootstrap._probe_tool_version",
                    return_value="hf 1.0.0",
                ),
            ):
                result = install_tool(project_root, "hf", user_bin_dir=user_bin_dir)

            launcher = user_bin_dir / "hf"
            support_home = support_root / "hf" / "home"
            self.assertEqual(result.record.tool, "hf")
            self.assertTrue(launcher.exists())
            self.assertTrue((support_home / ".hf-cli" / "venv" / "bin" / "python").exists())
            self.assertIn(str(support_home), launcher.read_text(encoding="utf-8"))


class RemoteBackendBootstrapTests(unittest.TestCase):
    def test_remote_backend_acquisition_downloads_pinned_prebuilt_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            plan = plan_llama_cpp_acquisition(_fake_hardware_profile("cpu"))

            fake_asset = type(
                "FakeAsset",
                (),
                {
                    "url": "https://example.invalid/llama.zip",
                    "archive_kind": "zip",
                    "checksum": None,
                },
            )()

            with (
                patch("aistackd.runtime.backends.resolve_llama_cpp_prebuilt_asset", return_value=fake_asset),
                patch("aistackd.runtime.backends.download_url_to_path", side_effect=_fake_backend_zip_download),
            ):
                result = acquire_managed_llama_cpp_installation(project_root, plan)

            self.assertEqual(result.strategy, "downloaded_prebuilt")
            self.assertEqual(result.installation.acquisition_method, "downloaded_prebuilt")
            self.assertTrue(Path(result.installation.server_binary).exists())

    def test_remote_backend_source_fallback_requires_compiler_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            plan = plan_llama_cpp_acquisition(_fake_hardware_profile("rocm"))

            with (
                patch("aistackd.runtime.backends.resolve_llama_cpp_prebuilt_asset", return_value=None),
                patch("aistackd.runtime.backends.download_url_to_path", side_effect=_fake_backend_source_download),
                patch(
                    "aistackd.runtime.backends.shutil.which",
                    side_effect=lambda command: None if command in {"gcc", "g++", "clang", "clang++"} else f"/usr/bin/{command}",
                ),
            ):
                with self.assertRaisesRegex(Exception, "gcc/g\\+\\+ or clang/clang\\+\\+"):
                    acquire_managed_llama_cpp_installation(project_root, plan)

    def test_remote_backend_source_fallback_builds_from_downloaded_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            plan = plan_llama_cpp_acquisition(_fake_hardware_profile("rocm"))
            captured_env: dict[str, str] = {}

            with (
                patch("aistackd.runtime.backends.resolve_llama_cpp_prebuilt_asset", return_value=None),
                patch("aistackd.runtime.backends.download_url_to_path", side_effect=_fake_backend_source_download),
                patch(
                    "aistackd.runtime.backends.subprocess.run",
                    side_effect=lambda command, **kwargs: _fake_backend_subprocess_run(command, captured_env, **kwargs),
                ),
            ):
                result = acquire_managed_llama_cpp_installation(project_root, plan, jobs=2)

            self.assertEqual(result.strategy, "downloaded_source_build")
            self.assertEqual(result.installation.acquisition_method, "downloaded_source_build")
            self.assertEqual(captured_env["HSA_OVERRIDE_GFX_VERSION"], "11.0.0")
            self.assertTrue(Path(result.installation.server_binary).exists())


def _fake_tool_download(url: str, destination: Path) -> str:
    destination.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return "tool-checksum"


def _fake_tool_installer_run(script_path: Path, spec: BootstrapToolSpec, staged_home: Path) -> None:
    staged_bin = staged_home / ".local" / "bin"
    staged_bin.mkdir(parents=True, exist_ok=True)
    binary_path = staged_bin / spec.name
    binary_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary_path.chmod(0o755)


def _fake_hf_installer_run(script_path: Path, spec: BootstrapToolSpec, staged_home: Path) -> None:
    venv_bin = staged_home / ".hf-cli" / "venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    python_path = venv_bin / "python"
    python_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_path.chmod(0o755)

    staged_bin = staged_home / ".local" / "bin"
    staged_bin.mkdir(parents=True, exist_ok=True)
    launcher = staged_bin / "hf"
    launcher.write_text(
        (
            f"#!{python_path}\n"
            "import sys\n"
            "from huggingface_hub.cli.hf import main\n"
            "if __name__ == '__main__':\n"
            "    sys.exit(main())\n"
        ),
        encoding="utf-8",
    )
    launcher.chmod(0o755)


def _fake_backend_zip_download(url: str, destination: Path) -> str:
    with zipfile.ZipFile(destination, "w") as handle:
        handle.writestr("llama.cpp/bin/llama-server", "#!/bin/sh\nexit 0\n")
        handle.writestr("llama.cpp/bin/llama-cli", "#!/bin/sh\nexit 0\n")
    return "zip-checksum"


def _fake_backend_source_download(url: str, destination: Path) -> str:
    with tarfile.open(destination, "w:gz") as handle:
        cmake_contents = b"cmake_minimum_required(VERSION 3.20)\nproject(llama_cpp)\n"
        cmake_info = tarfile.TarInfo(name="llama.cpp-source/CMakeLists.txt")
        cmake_info.size = len(cmake_contents)
        handle.addfile(cmake_info, io.BytesIO(cmake_contents))
    return "source-checksum"


def _fake_backend_subprocess_run(
    command: list[str],
    captured_env: dict[str, str],
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    env = kwargs.get("env")
    if isinstance(env, dict):
        captured_env.update({key: str(value) for key, value in env.items()})

    if command[:2] == ["cmake", "-S"]:
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    if command[:2] == ["cmake", "--build"]:
        build_root = Path(command[2])
        bin_dir = build_root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for binary_name in ("llama-server", "llama-cli"):
            path = bin_dir / binary_name
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    raise AssertionError(f"unexpected command: {command}")


def _fake_hardware_profile(flavor: str) -> HardwareProfile:
    return HardwareProfile(
        schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
        detector="llmfit",
        backend="amd" if flavor == "rocm" else "cpu",
        acceleration_api=flavor,
        target="gfx1100" if flavor == "rocm" else "",
        cmake_flags=("-DGGML_HIP=ON",) if flavor == "rocm" else (),
        gpu_layers=99 if flavor != "cpu" else 0,
        hsa_override_gfx_version="11.0.0" if flavor == "rocm" else "",
    )
