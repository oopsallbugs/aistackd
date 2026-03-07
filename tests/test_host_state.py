"""Host-state contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aistackd.models.sources import resolve_source_model
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

