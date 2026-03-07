"""Sync write and adapter contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aistackd.frontends.sync import SyncManifest, SyncRequest, apply_sync_manifest
from aistackd.runtime.config import RuntimeConfig
from aistackd.state.profiles import Profile


class SyncWriteTests(unittest.TestCase):
    def test_apply_sync_manifest_is_idempotent_for_managed_files(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000",
            api_key_env="AISTACKD_API_KEY",
        )
        runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode"))
        manifest = SyncManifest.create(runtime_config, SyncRequest.create(runtime_config.frontend_targets))

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            first_result = apply_sync_manifest(project_root, manifest)
            first_opencode = (project_root / "opencode.json").read_text(encoding="utf-8")
            first_codex = (project_root / ".codex" / "aistackd.json").read_text(encoding="utf-8")

            second_result = apply_sync_manifest(project_root, manifest)
            second_opencode = (project_root / "opencode.json").read_text(encoding="utf-8")
            second_codex = (project_root / ".codex" / "aistackd.json").read_text(encoding="utf-8")

            self.assertEqual(first_opencode, second_opencode)
            self.assertEqual(first_codex, second_codex)
            self.assertEqual(
                first_result.ownership_manifest_path,
                second_result.ownership_manifest_path,
            )

    def test_sync_write_result_reports_written_paths(self) -> None:
        profile = Profile(
            name="lab-host",
            base_url="http://10.0.0.25:8000",
            api_key_env="AISTACKD_API_KEY",
        )
        runtime_config = RuntimeConfig.for_client(profile, ("opencode",))
        manifest = SyncManifest.create(
            runtime_config,
            SyncRequest.create(runtime_config.frontend_targets, dry_run=False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = apply_sync_manifest(Path(tmpdir), manifest)

            payload = result.to_dict()
            self.assertEqual(payload["manifest"]["active_profile"], "lab-host")
            self.assertIn("opencode.json", "\n".join(payload["written_paths"]))
            ownership_payload = json.loads(Path(result.ownership_manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(ownership_payload["targets"][0]["frontend"], "opencode")
