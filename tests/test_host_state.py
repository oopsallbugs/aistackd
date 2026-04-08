"""Host-state contract tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import aistackd.state.host as host_state
from aistackd.models.sources import local_source_model
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.state.host import (
    HostBackendProcess,
    HostControlPlaneProcess,
    HostStateError,
    HostStateStore,
    InstalledToolRecord,
)


class HostStateTests(unittest.TestCase):
    def test_response_state_round_trips_and_prunes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))

            store.save_response_state("resp_old", "local-model", [{"role": "user", "content": "first"}], retention_limit=1)
            store.save_response_state("resp_new", "local-model", [{"role": "user", "content": "second"}], retention_limit=1)

            self.assertIsNone(store.load_response_state("resp_old"))
            persisted = store.load_response_state("resp_new")
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.response_id, "resp_new")
            self.assertEqual(persisted.model_name, "local-model")
            self.assertEqual(persisted.messages[0]["content"], "second")
            self.assertEqual(store.count_response_states(), 1)

    def test_response_state_rejects_unsafe_response_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))

            with self.assertRaisesRegex(HostStateError, "response_id must use only letters, numbers, underscores, or hyphens"):
                store.save_response_state("../escape", "local-model", [{"role": "user", "content": "bad"}])

    def test_install_and_activate_model_round_trips_host_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m", source="llmfit")
            artifact_path = _create_fake_gguf(Path(tmpdir), "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")

            record, created = store.install_model(
                source_model,
                acquisition_source="local",
                acquisition_method="explicit_local_gguf",
                artifact_path=artifact_path,
                size_bytes=artifact_path.stat().st_size,
                sha256=_sha256(artifact_path),
            )
            runtime_state = store.activate_model(record.model)

            self.assertTrue(created)
            self.assertEqual(record.source, "local")
            self.assertEqual(runtime_state.active_model, record.model)
            self.assertEqual(runtime_state.active_source, "local")
            self.assertEqual(runtime_state.activation_state, "ready")
            self.assertEqual(len(runtime_state.installed_models), 1)

            receipt_payload = json.loads(Path(record.receipt_path).read_text(encoding="utf-8"))
            self.assertEqual(receipt_payload["model"], record.model)
            self.assertEqual(receipt_payload["source"], "local")
            self.assertEqual(receipt_payload["catalog_source"], "llmfit")
            self.assertEqual(receipt_payload["acquisition_method"], "explicit_local_gguf")

    def test_runtime_state_marks_missing_artifact_when_managed_model_file_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = local_source_model("deepseek-r1-distill-qwen-7b-q4-k-m", source="llmfit")
            artifact_path = _create_fake_gguf(Path(tmpdir), "DeepSeek-R1-Distill-Qwen-7B.Q4_K_M.gguf")

            record, created = store.install_model(
                source_model,
                acquisition_source="local",
                acquisition_method="explicit_local_gguf",
                artifact_path=artifact_path,
                size_bytes=artifact_path.stat().st_size,
                sha256=_sha256(artifact_path),
            )
            managed_artifact = Path(record.artifact_path)
            managed_artifact.unlink()
            runtime_state = store.activate_model(record.model)

            self.assertTrue(created)
            self.assertEqual(record.source, "local")
            self.assertEqual(runtime_state.activation_state, "missing_artifact")
            self.assertEqual(runtime_state.active_source, "local")

    def test_persisted_backend_tuning_round_trips_and_survives_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            store.save_persisted_backend_tuning(
                context_size=16384,
                predict_limit=2048,
                parallel=2,
                batch_size=512,
                ubatch_size=256,
                gpu_layers=0,
                fit_target=0,
                no_kv_offload=False,
                no_op_offload=True,
                cache_ram=0,
            )

            (
                context_size,
                predict_limit,
                parallel,
                batch_size,
                ubatch_size,
                gpu_layers,
                fit_target,
                no_kv_offload,
                no_op_offload,
                cache_ram,
            ) = store.load_persisted_backend_tuning()

            self.assertEqual(context_size, 16384)
            self.assertEqual(predict_limit, 2048)
            self.assertEqual(parallel, 2)
            self.assertEqual(batch_size, 512)
            self.assertEqual(ubatch_size, 256)
            self.assertEqual(gpu_layers, 0)
            self.assertEqual(fit_target, 0)
            self.assertFalse(no_kv_offload)
            self.assertTrue(no_op_offload)
            self.assertEqual(cache_ram, 0)

            source_model = local_source_model("local-model", source="llmfit")
            artifact_path = _create_fake_gguf(Path(tmpdir), "Local-Model.Q4_K_M.gguf")
            record, _created = store.install_model(
                source_model,
                acquisition_source="local",
                acquisition_method="explicit_local_gguf",
                artifact_path=artifact_path,
                size_bytes=artifact_path.stat().st_size,
                sha256=_sha256(artifact_path),
            )

            runtime_state = store.activate_model(record.model)

            self.assertEqual(runtime_state.configured_backend_context_size, 16384)
            self.assertEqual(runtime_state.configured_backend_predict_limit, 2048)
            self.assertEqual(runtime_state.configured_backend_parallel, 2)
            self.assertEqual(runtime_state.configured_backend_batch_size, 512)
            self.assertEqual(runtime_state.configured_backend_ubatch_size, 256)
            self.assertEqual(runtime_state.configured_backend_gpu_layers, 0)
            self.assertEqual(runtime_state.configured_backend_fit_target, 0)
            self.assertFalse(runtime_state.configured_backend_no_kv_offload)
            self.assertTrue(runtime_state.configured_backend_no_op_offload)
            self.assertEqual(runtime_state.configured_backend_cache_ram, 0)

    def test_backend_installation_round_trips_through_host_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_root = _create_fake_backend_root(Path(tmpdir))
            store = HostStateStore(Path(tmpdir))
            discovery = discover_llama_cpp_installation(backend_root=backend_root)
            installation = adopt_backend_installation(discovery)

            created = store.save_backend_installation(installation)
            runtime_state = store.load_runtime_state()

            self.assertTrue(created)
            self.assertEqual(runtime_state.backend_status, "configured")
            self.assertIsNotNone(runtime_state.backend_installation)
            self.assertEqual(runtime_state.backend_installation.server_binary, installation.server_binary)

    def test_control_plane_process_round_trips_through_host_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            log_path = store.paths.control_plane_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")

            created = store.save_control_plane_process(
                HostControlPlaneProcess(
                    status="running",
                    pid=1234,
                    command=("python3", "-m", "aistackd", "host", "serve"),
                    bind_host="127.0.0.1",
                    port=8000,
                    log_path=str(log_path),
                    started_at="2026-03-08T00:00:00+00:00",
                )
            )

            persisted = store.load_control_plane_process()

            self.assertTrue(created)
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.pid, 1234)
            self.assertEqual(persisted.base_url, "http://127.0.0.1:8000")

    def test_backend_process_inferrs_limits_from_persisted_command(self) -> None:
        record = HostBackendProcess.from_dict(
            {
                "backend": "llama.cpp",
                "status": "running",
                "pid": 4242,
                "command": [
                    "/tmp/llama-server",
                    "--model",
                    "/tmp/model.gguf",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8011",
                    "--ctx-size",
                    "24576",
                    "--predict",
                    "4096",
                    "--parallel",
                    "1",
                ],
                "bind_host": "127.0.0.1",
                "port": 8011,
                "model": "local-model",
                "artifact_path": "/tmp/model.gguf",
                "server_binary": "/tmp/llama-server",
                "log_path": "/tmp/llama-cpp.log",
                "started_at": "2026-03-12T00:00:00+00:00",
            }
        )

        self.assertEqual(record.context_size, 24576)
        self.assertEqual(record.predict_limit, 4096)
        self.assertEqual(record.parallel, 1)

    def test_runtime_state_marks_stale_control_plane_process_as_exited(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            log_path = store.paths.control_plane_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")
            store.save_control_plane_process(
                HostControlPlaneProcess(
                    status="running",
                    pid=999999,
                    command=("python3", "-m", "aistackd", "host", "serve"),
                    bind_host="127.0.0.1",
                    port=8000,
                    log_path=str(log_path),
                    started_at="2026-03-08T00:00:00+00:00",
                )
            )

            with patch("aistackd.state.host._pid_exists", return_value=False):
                runtime_state = store.load_runtime_state()

            self.assertEqual(runtime_state.control_plane_process_status, "exited")
            self.assertIsNotNone(runtime_state.control_plane_process)
            assert runtime_state.control_plane_process is not None
            self.assertEqual(runtime_state.control_plane_process.status, "exited")

    def test_runtime_state_marks_backend_process_as_exited_when_pid_start_time_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            backend_log_path = store.paths.backend_log_path()
            backend_log_path.parent.mkdir(parents=True, exist_ok=True)
            backend_log_path.write_text("", encoding="utf-8")
            store.save_backend_process(
                HostBackendProcess(
                    backend="llama.cpp",
                    status="running",
                    pid=4242,
                    command=("llama-server", "--model", "/tmp/model.gguf"),
                    bind_host="127.0.0.1",
                    port=8011,
                    model="local-model",
                    artifact_path="/tmp/model.gguf",
                    server_binary="/tmp/llama-server",
                    log_path=str(backend_log_path),
                    started_at="2026-03-07T00:00:00+00:00",
                    pid_start_time_ticks=100,
                )
            )

            with (
                patch("aistackd.state.host._pid_exists", return_value=True),
                patch("aistackd.state.host.read_pid_start_time_ticks", return_value=200),
            ):
                runtime = store.load_runtime_state()

            self.assertEqual(runtime.backend_process_status, "exited")
            self.assertIsNotNone(runtime.backend_process)
            assert runtime.backend_process is not None
            self.assertEqual(runtime.backend_process.status, "exited")

    def test_runtime_state_marks_control_plane_process_as_exited_when_pid_start_time_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            log_path = store.paths.control_plane_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")
            store.save_control_plane_process(
                HostControlPlaneProcess(
                    status="running",
                    pid=1234,
                    command=("python3", "-m", "aistackd", "host", "serve"),
                    bind_host="127.0.0.1",
                    port=8000,
                    log_path=str(log_path),
                    started_at="2026-03-08T00:00:00+00:00",
                    pid_start_time_ticks=100,
                )
            )

            with (
                patch("aistackd.state.host._pid_exists", return_value=True),
                patch("aistackd.state.host.read_pid_start_time_ticks", return_value=200),
            ):
                runtime = store.load_runtime_state()

            self.assertEqual(runtime.control_plane_process_status, "exited")
            self.assertIsNotNone(runtime.control_plane_process)
            assert runtime.control_plane_process is not None
            self.assertEqual(runtime.control_plane_process.status, "exited")

    def test_host_state_storage_creates_managed_backends_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))

            store.ensure_storage()

            self.assertTrue(store.paths.managed_backends_dir.exists())
            self.assertTrue(store.paths.managed_models_dir.exists())
            self.assertTrue(store.paths.host_logs_dir.exists())
            self.assertTrue(store.paths.responses_state_dir.exists())
            self.assertTrue(store.paths.control_plane_process_path.parent.exists())

    def test_installed_tool_round_trips_through_host_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            record = InstalledToolRecord(
                tool="llmfit",
                executable_path=str(Path(tmpdir) / ".local" / "bin" / "llmfit"),
                version="llmfit 0.6.2",
                source_url="https://llmfit.axjns.dev/install.sh",
                checksum="abc123",
                installed_at="2026-03-10T00:00:00+00:00",
            )
            Path(record.executable_path).parent.mkdir(parents=True, exist_ok=True)
            Path(record.executable_path).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            created = store.save_installed_tool(record)
            persisted = store.load_installed_tool("llmfit")

            self.assertTrue(created)
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.executable_path, record.executable_path)
            self.assertEqual(persisted.version, "llmfit 0.6.2")

    def test_save_installed_tool_serializes_concurrent_inventory_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            first_record = _installed_tool_record(Path(tmpdir), "llmfit")
            second_record = _installed_tool_record(Path(tmpdir), "hf")
            entered_first_read = threading.Event()
            release_first_read = threading.Event()
            second_read_started = threading.Event()
            observed_reads = 0
            observed_reads_lock = threading.Lock()
            errors: list[Exception] = []
            original_load_json_object = host_state.load_json_object

            def controlled_load_json_object(path: Path) -> dict[str, object]:
                nonlocal observed_reads
                if path == store.paths.installed_tools_path:
                    with observed_reads_lock:
                        observed_reads += 1
                        current_read = observed_reads
                    if current_read == 1:
                        entered_first_read.set()
                        release_first_read.wait(timeout=2)
                    elif current_read == 2:
                        second_read_started.set()
                return original_load_json_object(path)

            def save_tool(record: InstalledToolRecord) -> None:
                try:
                    store.save_installed_tool(record)
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)

            with patch("aistackd.state.host.load_json_object", side_effect=controlled_load_json_object):
                first_thread = threading.Thread(target=save_tool, args=(first_record,))
                second_thread = threading.Thread(target=save_tool, args=(second_record,))
                first_thread.start()
                self.assertTrue(entered_first_read.wait(timeout=2))

                second_thread.start()
                self.assertFalse(second_read_started.wait(timeout=0.3))

                release_first_read.set()
                first_thread.join(timeout=2)
                second_thread.join(timeout=2)

            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual({record.tool for record in store.list_installed_tools()}, {"hf", "llmfit"})


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


def _installed_tool_record(root: Path, tool_name: str) -> InstalledToolRecord:
    executable_path = root / ".local" / "bin" / tool_name
    executable_path.parent.mkdir(parents=True, exist_ok=True)
    executable_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return InstalledToolRecord(
        tool=tool_name,
        executable_path=str(executable_path),
        version=f"{tool_name} 1.0.0",
        source_url=f"https://example.test/{tool_name}/install.sh",
        checksum=f"{tool_name}-checksum",
        installed_at="2026-03-10T00:00:00+00:00",
    )
