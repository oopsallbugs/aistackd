"""Managed control-plane process lifecycle tests."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.models.sources import local_source_model
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.runtime.control_plane_process import (
    build_control_plane_command,
    launch_control_plane_process,
    stop_current_control_plane_process,
)
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostControlPlaneProcess, HostStateStore


class ControlPlaneProcessRuntimeTests(unittest.TestCase):
    def test_build_control_plane_command_includes_backend_limits(self) -> None:
        command = build_control_plane_command(
            Path("/tmp/project"),
            HostServiceConfig(backend_context_size=16384, backend_predict_limit=2048),
        )

        self.assertIn("--backend-context-size", command)
        self.assertIn("16384", command)
        self.assertIn("--backend-predict-limit", command)
        self.assertIn("2048", command)

    def test_launch_control_plane_process_persists_starting_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))
            fake_process = _FakePopen(pid=4321)

            with (
                patch("aistackd.runtime.control_plane_process.subprocess.Popen", return_value=fake_process),
                patch("aistackd.runtime.control_plane_process.time.sleep", return_value=None),
                patch("aistackd.state.host._pid_exists", return_value=True),
            ):
                running_process = launch_control_plane_process(Path(tmpdir), HostServiceConfig())
                runtime = store.load_runtime_state()

            self.assertEqual(running_process.record.status, "starting")
            self.assertEqual(runtime.control_plane_process_status, "starting")
            self.assertIsNotNone(runtime.control_plane_process)
            self.assertEqual(runtime.control_plane_process.pid, 4321)
            self.assertTrue(Path(runtime.control_plane_process.log_path).exists())

    def test_stop_current_control_plane_process_marks_service_as_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))
            log_path = store.paths.control_plane_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")
            store.save_control_plane_process(
                HostControlPlaneProcess(
                    status="running",
                    pid=5555,
                    command=("python3", "-m", "aistackd", "host", "serve"),
                    bind_host="127.0.0.1",
                    port=8000,
                    log_path=str(log_path),
                    started_at="2026-03-08T00:00:00+00:00",
                )
            )

            with patch("aistackd.runtime.control_plane_process._terminate_pid", return_value=-15) as terminate_mock:
                stopped_record = stop_current_control_plane_process(store)

            self.assertIsNotNone(stopped_record)
            assert stopped_record is not None
            self.assertEqual(stopped_record.status, "stopped")
            terminate_mock.assert_called_once_with(5555)
            runtime = store.load_runtime_state()
            self.assertEqual(runtime.control_plane_process_status, "stopped")


class _FakePopen:
    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self._poll_result: int | None = None

    def poll(self) -> int | None:
        return self._poll_result


def _create_ready_host_state(project_root: Path) -> HostStateStore:
    store = HostStateStore(project_root)
    source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m", source="llmfit")
    artifact_path = _create_fake_gguf(project_root, "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
    record, _ = store.install_model(
        source_model,
        acquisition_source="local",
        acquisition_method="explicit_local_gguf",
        artifact_path=artifact_path,
        size_bytes=artifact_path.stat().st_size,
        sha256=_sha256(artifact_path),
    )
    store.activate_model(record.model)
    backend_root = _create_fake_backend_root(project_root)
    store.save_backend_installation(
        adopt_backend_installation(discover_llama_cpp_installation(backend_root=backend_root))
    )
    return store


def _create_fake_backend_root(root: Path) -> Path:
    backend_root = root / "llama.cpp"
    bin_dir = backend_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for binary_name in ("llama-server", "llama-cli"):
        path = bin_dir / binary_name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return backend_root


def _create_fake_gguf(root: Path, filename: str) -> Path:
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_root / filename
    artifact_path.write_bytes(b"GGUF\x00test-model\n")
    return artifact_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
