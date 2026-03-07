"""Host runtime validation tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.models.sources import resolve_source_model
from aistackd.runtime.host import HostServiceConfig, validate_host_runtime
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
            self.assertIn("no active model is configured for host runtime", result.errors)

    def test_validate_host_runtime_succeeds_when_active_model_and_api_key_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = resolve_source_model("qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertIsNotNone(source_model)
            record, _ = store.install_model(source_model)
            store.activate_model(record.model)

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

