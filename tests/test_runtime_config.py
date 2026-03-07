"""Runtime config and sync manifest contract tests."""

from __future__ import annotations

import unittest

from aistackd.frontends.sync import SyncManifest, SyncRequest
from aistackd.runtime.config import CURRENT_RUNTIME_CONFIG_SCHEMA_VERSION, RuntimeConfig
from aistackd.state.profiles import Profile


class RuntimeConfigTests(unittest.TestCase):
    def test_runtime_config_is_derived_from_profile(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000/",
            api_key_env="AISTACKD_API_KEY",
            role_hint="host",
        )

        runtime_config = RuntimeConfig.for_client(profile, ("codex",))

        self.assertEqual(runtime_config.schema_version, CURRENT_RUNTIME_CONFIG_SCHEMA_VERSION)
        self.assertEqual(runtime_config.mode, "client")
        self.assertEqual(runtime_config.active_profile, "local")
        self.assertEqual(runtime_config.base_url, "http://127.0.0.1:8000")
        self.assertEqual(runtime_config.responses_base_url, "http://127.0.0.1:8000/v1")
        self.assertEqual(runtime_config.frontend_targets, ("codex",))

    def test_sync_manifest_uses_runtime_config_targets(self) -> None:
        profile = Profile(
            name="lab-host",
            base_url="http://10.0.0.25:8000",
            api_key_env="AISTACKD_LAB_HOST_API_KEY",
        )
        runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode"))
        request = SyncRequest.create(runtime_config.frontend_targets)

        manifest = SyncManifest.create(runtime_config, request)

        self.assertEqual(manifest.active_profile, "lab-host")
        self.assertEqual(manifest.mode, "client")
        self.assertTrue(manifest.dry_run)
        self.assertEqual(len(manifest.targets), 2)
        self.assertEqual(manifest.targets[0].provider_base_url, "http://10.0.0.25:8000/v1")
        self.assertEqual(manifest.targets[0].api_key_env, "AISTACKD_LAB_HOST_API_KEY")
