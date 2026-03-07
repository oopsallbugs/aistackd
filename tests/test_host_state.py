"""Host-state contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aistackd.models.sources import resolve_source_model
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.state.host import HostStateStore


class HostStateTests(unittest.TestCase):
    def test_install_and_activate_model_round_trips_host_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = resolve_source_model("qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertIsNotNone(source_model)

            record, created = store.install_model(source_model)
            runtime_state = store.activate_model(record.model)

            self.assertTrue(created)
            self.assertEqual(record.source, "llmfit")
            self.assertEqual(runtime_state.active_model, record.model)
            self.assertEqual(runtime_state.active_source, "llmfit")
            self.assertEqual(runtime_state.activation_state, "ready")
            self.assertEqual(len(runtime_state.installed_models), 1)

            receipt_payload = json.loads(Path(record.receipt_path).read_text(encoding="utf-8"))
            self.assertEqual(receipt_payload["model"], record.model)
            self.assertEqual(receipt_payload["source"], "llmfit")

    def test_install_prefers_primary_source_when_name_exists_in_both_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = resolve_source_model("deepseek-r1-distill-qwen-7b-q4-k-m")
            self.assertIsNotNone(source_model)

            record, created = store.install_model(source_model)

            self.assertTrue(created)
            self.assertEqual(record.source, "llmfit")
            self.assertEqual(len(store.list_installed_models()), 1)

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


def _create_fake_backend_root(root: Path) -> Path:
    backend_root = root / "llama.cpp"
    bin_dir = backend_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for binary_name in ("llama-server", "llama-cli"):
        path = bin_dir / binary_name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return backend_root
