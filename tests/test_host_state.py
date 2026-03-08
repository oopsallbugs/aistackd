"""Host-state contract tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.models.sources import local_source_model
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.state.host import HostControlPlaneProcess, HostStateStore


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

    def test_host_state_storage_creates_managed_backends_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))

            store.ensure_storage()

            self.assertTrue(store.paths.managed_backends_dir.exists())
            self.assertTrue(store.paths.managed_models_dir.exists())
            self.assertTrue(store.paths.host_logs_dir.exists())
            self.assertTrue(store.paths.responses_state_dir.exists())
            self.assertTrue(store.paths.control_plane_process_path.parent.exists())


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
