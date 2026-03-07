"""Backend discovery and host inspection tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.runtime.backends import discover_llama_cpp_installation
from aistackd.runtime.prereqs import inspect_host_environment


class BackendRuntimeTests(unittest.TestCase):
    def test_discover_llama_cpp_installation_from_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_root = _create_fake_backend_root(Path(tmpdir))

            discovery = discover_llama_cpp_installation(backend_root=backend_root)

            self.assertTrue(discovery.found)
            self.assertEqual(discovery.discovery_mode, "explicit_root")
            self.assertEqual(discovery.backend_root, str(backend_root))
            self.assertTrue(discovery.server_binary.endswith("llama-server"))
            self.assertTrue(discovery.cli_binary.endswith("llama-cli"))

    def test_inspect_host_environment_reports_prerequisite_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_root = _create_fake_backend_root(Path(tmpdir))

            with patch(
                "aistackd.runtime.prereqs.shutil.which",
                side_effect=lambda command: None if command == "node" else f"/usr/bin/{command}",
            ):
                report = inspect_host_environment(backend_root=backend_root)

            self.assertFalse(report.ok)
            self.assertFalse(report.prerequisites_ok)
            self.assertTrue(report.backend_discovery.found)
            checks = {check.name: check for check in report.prerequisite_checks}
            self.assertFalse(checks["node"].ok)
            self.assertTrue(checks["cmake"].ok)
            self.assertTrue(checks["make"].ok)


def _create_fake_backend_root(root: Path) -> Path:
    backend_root = root / "llama.cpp"
    bin_dir = backend_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for binary_name in ("llama-server", "llama-cli"):
        path = bin_dir / binary_name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return backend_root

