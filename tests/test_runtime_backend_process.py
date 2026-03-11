"""Managed backend-process lifecycle tests."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.models.sources import local_source_model
from aistackd.runtime.backend_process import (
    build_backend_launch_plan,
    launch_managed_backend_process,
    restart_managed_backend_process,
    stop_current_managed_backend_process,
    stop_managed_backend_process,
)
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostBackendProcess, HostStateStore


class BackendProcessRuntimeTests(unittest.TestCase):
    def test_build_backend_launch_plan_uses_active_model_and_backend_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))

            plan = build_backend_launch_plan(store, HostServiceConfig())

            self.assertTrue(plan.command[0].endswith("llama-server"))
            self.assertIn("--model", plan.command)
            self.assertIn("--host", plan.command)
            self.assertIn("--port", plan.command)
            self.assertIn("--ctx-size", plan.command)
            self.assertIn("--predict", plan.command)
            self.assertEqual(plan.model, "qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertTrue(plan.artifact_path.endswith(".gguf"))
            self.assertTrue(plan.log_path.endswith(".aistackd/host/logs/llama-cpp.log"))
            self.assertEqual(plan.context_size, 32768)
            self.assertEqual(plan.predict_limit, 8192)

    def test_launch_managed_backend_process_persists_running_process_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))
            fake_process = _FakePopen(pid=4321)

            with (
                patch("aistackd.runtime.backend_process.subprocess.Popen", return_value=fake_process),
                patch("aistackd.runtime.backend_process.time.sleep", return_value=None),
                patch("aistackd.state.host._pid_exists", return_value=True),
            ):
                running_process = launch_managed_backend_process(store, HostServiceConfig())
                runtime = store.load_runtime_state()

            self.assertEqual(running_process.record.status, "running")
            self.assertEqual(runtime.backend_process_status, "running")
            self.assertIsNotNone(runtime.backend_process)
            self.assertEqual(runtime.backend_process.pid, 4321)
            self.assertTrue(Path(runtime.backend_process.log_path).exists())
            persisted_record = store.load_backend_process()
            self.assertIsNotNone(persisted_record)
            self.assertEqual(persisted_record.status, "running")

    def test_stop_managed_backend_process_marks_backend_as_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))
            fake_process = _FakePopen(pid=5555)

            with (
                patch("aistackd.runtime.backend_process.subprocess.Popen", return_value=fake_process),
                patch("aistackd.runtime.backend_process.time.sleep", return_value=None),
                patch("aistackd.state.host._pid_exists", return_value=True),
            ):
                running_process = launch_managed_backend_process(store, HostServiceConfig())
                stopped_record = stop_managed_backend_process(store, running_process)
                runtime = store.load_runtime_state()

            self.assertTrue(fake_process.terminate_called)
            self.assertEqual(stopped_record.status, "stopped")
            self.assertEqual(runtime.backend_process_status, "stopped")
            self.assertIsNotNone(runtime.backend_process)
            self.assertEqual(runtime.backend_process.exit_code, -15)

    def test_runtime_state_reports_exited_backend_when_pid_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))
            backend_log_path = store.paths.backend_log_path()
            backend_log_path.parent.mkdir(parents=True, exist_ok=True)
            backend_log_path.write_text("", encoding="utf-8")
            store.save_backend_process(
                HostBackendProcess(
                    backend="llama.cpp",
                    status="running",
                    pid=999999,
                    command=("llama-server", "--model", "/tmp/model.gguf"),
                    bind_host="127.0.0.1",
                    port=8011,
                    model="qwen2.5-coder-7b-instruct-q4-k-m",
                    artifact_path="/tmp/model.gguf",
                    server_binary="/tmp/llama-server",
                    log_path=str(backend_log_path),
                    started_at="2026-03-07T00:00:00+00:00",
                )
            )

            runtime = store.load_runtime_state()

            self.assertEqual(runtime.backend_process_status, "exited")
            self.assertIsNotNone(runtime.backend_process)
            self.assertEqual(runtime.backend_process.status, "exited")
            self.assertIsNotNone(runtime.backend_process.stopped_at)
            persisted_record = store.load_backend_process()
            self.assertIsNotNone(persisted_record)
            self.assertEqual(persisted_record.status, "exited")

    def test_stop_current_managed_backend_process_stops_persisted_running_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))
            backend_log_path = store.paths.backend_log_path()
            backend_log_path.parent.mkdir(parents=True, exist_ok=True)
            backend_log_path.write_text("", encoding="utf-8")
            store.save_backend_process(
                HostBackendProcess(
                    backend="llama.cpp",
                    status="running",
                    pid=4444,
                    command=("llama-server", "--model", "/tmp/model.gguf"),
                    bind_host="127.0.0.1",
                    port=8011,
                    model="qwen2.5-coder-7b-instruct-q4-k-m",
                    artifact_path="/tmp/model.gguf",
                    server_binary="/tmp/llama-server",
                    log_path=str(backend_log_path),
                    started_at="2026-03-07T00:00:00+00:00",
                )
            )

            with (
                patch("aistackd.state.host._pid_exists", return_value=True),
                patch("aistackd.runtime.backend_process._terminate_pid", return_value=-15) as terminate_mock,
            ):
                stopped_record = stop_current_managed_backend_process(store)

            self.assertIsNotNone(stopped_record)
            self.assertEqual(stopped_record.status, "stopped")
            terminate_mock.assert_called_once_with(4444)
            runtime = store.load_runtime_state()
            self.assertEqual(runtime.backend_process_status, "stopped")

    def test_restart_managed_backend_process_replaces_existing_backend_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir))
            backend_log_path = store.paths.backend_log_path()
            backend_log_path.parent.mkdir(parents=True, exist_ok=True)
            backend_log_path.write_text("", encoding="utf-8")
            store.save_backend_process(
                HostBackendProcess(
                    backend="llama.cpp",
                    status="running",
                    pid=4444,
                    command=("llama-server", "--model", "/tmp/model.gguf"),
                    bind_host="127.0.0.1",
                    port=8011,
                    model="qwen2.5-coder-7b-instruct-q4-k-m",
                    artifact_path="/tmp/model.gguf",
                    server_binary="/tmp/llama-server",
                    log_path=str(backend_log_path),
                    started_at="2026-03-07T00:00:00+00:00",
                )
            )
            fake_process = _FakePopen(pid=5555)

            with (
                patch("aistackd.state.host._pid_exists", return_value=True),
                patch("aistackd.runtime.backend_process._terminate_pid", return_value=-15) as terminate_mock,
                patch("aistackd.runtime.backend_process.subprocess.Popen", return_value=fake_process),
                patch("aistackd.runtime.backend_process.time.sleep", return_value=None),
                patch("aistackd.runtime.backend_process._pid_exists", side_effect=lambda pid: pid == 5555),
            ):
                running_process = restart_managed_backend_process(store, HostServiceConfig())
                runtime = store.load_runtime_state()

            self.assertEqual(running_process.record.pid, 5555)
            terminate_mock.assert_called_once_with(4444)
            self.assertEqual(runtime.backend_process_status, "running")
            self.assertIsNotNone(runtime.backend_process)
            self.assertEqual(runtime.backend_process.pid, 5555)


class _FakePopen:
    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self._poll_result: int | None = None
        self.terminate_called = False
        self.kill_called = False

    def poll(self) -> int | None:
        return self._poll_result

    def terminate(self) -> None:
        self.terminate_called = True
        self._poll_result = -15

    def wait(self, timeout: float | None = None) -> int:
        return self._poll_result if self._poll_result is not None else 0

    def kill(self) -> None:
        self.kill_called = True
        self._poll_result = -9


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
