"""Host runtime validation tests."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.models.sources import local_source_model
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.runtime.host import HostServiceConfig, validate_backend_runtime, validate_host_runtime
from aistackd.state.host import HostStateStore


class HostRuntimeTests(unittest.TestCase):
    def test_validate_host_runtime_reports_missing_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_host_runtime(
                HostStateStore(Path(tmpdir)),
                HostServiceConfig(bind_host="127.0.0.1", port=8000, api_key_env="AISTACKD_API_KEY"),
            )

            self.assertFalse(result.ok)
            self.assertIn("api key environment variable 'AISTACKD_API_KEY' is not set or empty", result.errors)
            self.assertIn("no installed models are available for host runtime", result.errors)
            self.assertIn("no backend installation is configured for host runtime", result.errors)
            self.assertIn("no active model is configured for host runtime", result.errors)

    def test_validate_host_runtime_succeeds_when_active_model_and_api_key_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m", source="llmfit")
            artifact_path = _create_fake_gguf(Path(tmpdir), "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
            record, _ = store.install_model(
                source_model,
                acquisition_source="local",
                acquisition_method="explicit_local_gguf",
                artifact_path=artifact_path,
                size_bytes=artifact_path.stat().st_size,
                sha256=_sha256(artifact_path),
            )
            store.activate_model(record.model)
            backend_root = _create_fake_backend_root(Path(tmpdir))
            store.save_backend_installation(
                adopt_backend_installation(discover_llama_cpp_installation(backend_root=backend_root))
            )

            with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                result = validate_host_runtime(
                    store,
                    HostServiceConfig(bind_host="127.0.0.1", port=8000, api_key_env="AISTACKD_API_KEY"),
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.service.base_url, "http://127.0.0.1:8000")
            self.assertEqual(result.service.responses_base_url, "http://127.0.0.1:8000/v1")
            self.assertEqual(result.runtime.active_model, record.model)
            self.assertEqual(result.errors, ())

    def test_validate_backend_runtime_does_not_require_control_plane_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m", source="llmfit")
            artifact_path = _create_fake_gguf(Path(tmpdir), "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
            record, _ = store.install_model(
                source_model,
                acquisition_source="local",
                acquisition_method="explicit_local_gguf",
                artifact_path=artifact_path,
                size_bytes=artifact_path.stat().st_size,
                sha256=_sha256(artifact_path),
            )
            store.activate_model(record.model)
            backend_root = _create_fake_backend_root(Path(tmpdir))
            store.save_backend_installation(
                adopt_backend_installation(discover_llama_cpp_installation(backend_root=backend_root))
            )

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("AISTACKD_API_KEY", None)
                result = validate_backend_runtime(
                    store,
                    HostServiceConfig(bind_host="127.0.0.1", port=8000, api_key_env="AISTACKD_API_KEY"),
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.errors, ())


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
