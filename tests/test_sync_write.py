"""Sync write and adapter contract tests."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from aistackd.frontends.sync import SyncManifest, SyncOwnershipManifest, SyncRequest, apply_sync_manifest
from aistackd.runtime.config import RuntimeConfig
from aistackd.skills.project_local import PROJECT_LOCAL_SKILL_PROVENANCE_FILE_NAME
from aistackd.state.profiles import Profile


class SyncWriteTests(unittest.TestCase):
    def test_apply_sync_manifest_is_idempotent_for_managed_files(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000",
            api_key_env="AISTACKD_API_KEY",
            model="local-model",
        )
        runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode", "openhands"))
        manifest = SyncManifest.create(runtime_config, SyncRequest.create(runtime_config.frontend_targets))

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            first_result = apply_sync_manifest(project_root, manifest)
            first_opencode = (project_root / "opencode.json").read_text(encoding="utf-8")
            first_codex = (project_root / ".codex" / "config.toml").read_text(encoding="utf-8")
            first_openhands = (project_root / ".openhands" / "config.toml").read_text(encoding="utf-8")
            first_codex_tool = (project_root / ".codex" / "tools" / "runtime-status.py").read_text(encoding="utf-8")

            second_result = apply_sync_manifest(project_root, manifest)
            second_opencode = (project_root / "opencode.json").read_text(encoding="utf-8")
            second_codex = (project_root / ".codex" / "config.toml").read_text(encoding="utf-8")
            second_openhands = (project_root / ".openhands" / "config.toml").read_text(encoding="utf-8")
            second_codex_tool = (project_root / ".codex" / "tools" / "runtime-status.py").read_text(encoding="utf-8")

            self.assertEqual(first_opencode, second_opencode)
            self.assertEqual(first_codex, second_codex)
            self.assertEqual(first_openhands, second_openhands)
            self.assertEqual(first_codex_tool, second_codex_tool)
            self.assertEqual(
                first_result.ownership_manifest_path,
                second_result.ownership_manifest_path,
            )

    def test_sync_write_result_reports_written_paths(self) -> None:
        profile = Profile(
            name="lab-host",
            base_url="http://10.0.0.25:8000",
            api_key_env="AISTACKD_API_KEY",
            model="lab-model",
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
            self.assertIn(".opencode/tools/runtime-status.py", "\n".join(payload["written_paths"]))
            self.assertIn(".opencode/tools/responses-smoke.py", "\n".join(payload["written_paths"]))
            self.assertIn(".opencode/tools/runtime-wait.py", "\n".join(payload["written_paths"]))
            self.assertIn(".opencode/tools/frontend-smoke.py", "\n".join(payload["written_paths"]))
            self.assertIn(".opencode/tools/tool-call-demo.py", "\n".join(payload["written_paths"]))
            self.assertEqual(
                payload["manifest"]["targets"][0]["provider_payload"]["provider"]["aistackd"]["models"]["lab-model"]["name"],
                "lab-model",
            )
            self.assertEqual(
                payload["manifest"]["targets"][0]["provider_payload"]["provider"]["aistackd"]["options"]["apiKey"],
                "{env:AISTACKD_API_KEY}",
            )
            self.assertEqual(
                payload["manifest"]["targets"][0]["provider_payload"]["provider"]["aistackd"]["models"]["lab-model"]["limit"]["context"],
                24576,
            )
            self.assertEqual(
                payload["manifest"]["targets"][0]["provider_payload"]["provider"]["aistackd"]["models"]["lab-model"]["limit"]["output"],
                4096,
            )
            ownership_payload = json.loads(Path(result.ownership_manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(ownership_payload["targets"][0]["frontend"], "opencode")

    def test_sync_write_result_reports_openhands_paths(self) -> None:
        profile = Profile(
            name="lab-host",
            base_url="http://10.0.0.25:8000",
            api_key_env="AISTACKD_API_KEY",
            model="lab-model",
        )
        runtime_config = RuntimeConfig.for_client(profile, ("openhands",))
        manifest = SyncManifest.create(
            runtime_config,
            SyncRequest.create(runtime_config.frontend_targets, dry_run=False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = apply_sync_manifest(Path(tmpdir), manifest)

            payload = result.to_dict()
            self.assertIn(".openhands/config.toml", "\n".join(payload["written_paths"]))
            self.assertIn(".openhands/microagents/find-skills.md", "\n".join(payload["written_paths"]))
            self.assertEqual(payload["manifest"]["targets"][0]["baseline_tools"], [])
            self.assertEqual(
                payload["manifest"]["targets"][0]["provider_payload"]["llm"]["model"],
                "openai/lab-model",
            )

    def test_sync_write_prunes_removed_target_paths_and_preserves_unmanaged_config(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000",
            api_key_env="AISTACKD_API_KEY",
            model="local-model",
        )
        full_runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode"))
        codex_only_runtime_config = RuntimeConfig.for_client(profile, ("codex",))

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            opencode_path = project_root / "opencode.json"
            opencode_path.write_text(
                json.dumps(
                    {
                        "$schema": "https://opencode.ai/config.json",
                        "custom": {"keep": True},
                        "provider": {"existing": {"name": "keep"}},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            full_manifest = SyncManifest.create(
                full_runtime_config,
                SyncRequest.create(full_runtime_config.frontend_targets, dry_run=False),
            )
            apply_sync_manifest(project_root, full_manifest)

            unmanaged_opencode_skill_dir = project_root / ".opencode" / "skills" / "custom-local"
            unmanaged_opencode_skill_dir.mkdir(parents=True, exist_ok=True)
            (unmanaged_opencode_skill_dir / "SKILL.md").write_text(
                "name: custom-local\n",
                encoding="utf-8",
            )

            codex_only_manifest = SyncManifest.create(
                codex_only_runtime_config,
                SyncRequest.create(codex_only_runtime_config.frontend_targets, dry_run=False),
            )
            result = apply_sync_manifest(project_root, codex_only_manifest)

            cleaned_opencode_payload = json.loads(opencode_path.read_text(encoding="utf-8"))
            self.assertEqual(cleaned_opencode_payload["custom"], {"keep": True})
            self.assertEqual(cleaned_opencode_payload["provider"], {"existing": {"name": "keep"}})
            self.assertNotIn("model", cleaned_opencode_payload)
            self.assertFalse((project_root / ".opencode" / "skills" / "find-skills" / "SKILL.md").exists())
            self.assertFalse((project_root / ".opencode" / "tools" / "runtime-status.py").exists())
            self.assertFalse((project_root / ".opencode" / "tools" / "responses-smoke.py").exists())
            self.assertFalse((project_root / ".opencode" / "tools" / "runtime-wait.py").exists())
            self.assertFalse((project_root / ".opencode" / "tools" / "frontend-smoke.py").exists())
            self.assertFalse((project_root / ".opencode" / "tools" / "tool-call-demo.py").exists())
            self.assertTrue((project_root / ".opencode" / "skills" / "custom-local" / "SKILL.md").exists())
            self.assertTrue((project_root / ".codex" / "skills" / "find-skills" / "SKILL.md").exists())
            self.assertTrue((project_root / ".codex" / "tools" / "runtime-status.py").exists())
            self.assertTrue((project_root / ".codex" / "tools" / "responses-smoke.py").exists())
            self.assertTrue((project_root / ".codex" / "tools" / "runtime-wait.py").exists())
            self.assertTrue((project_root / ".codex" / "tools" / "frontend-smoke.py").exists())
            self.assertTrue((project_root / ".codex" / "tools" / "tool-call-demo.py").exists())
            self.assertIn(str(opencode_path), result.removed_paths)

            ownership_manifest = SyncOwnershipManifest.load(project_root)
            self.assertIsNotNone(ownership_manifest)
            assert ownership_manifest is not None
            self.assertEqual(tuple(target.frontend for target in ownership_manifest.targets), ("codex",))

    def test_sync_write_prunes_codex_profile_and_preserves_unmanaged_codex_config(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000",
            api_key_env="AISTACKD_API_KEY",
            model="local-model",
        )
        full_runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode"))
        opencode_only_runtime_config = RuntimeConfig.for_client(profile, ("opencode",))

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            codex_path = project_root / ".codex" / "config.toml"
            codex_path.parent.mkdir(parents=True, exist_ok=True)
            codex_path.write_text(
                "\n".join(
                    (
                        'model_reasoning_effort = "high"',
                        "",
                        "[profiles.fast]",
                        'model = "gpt-5.4"',
                        "",
                        "[model_providers.existing]",
                        'name = "existing"',
                        'base_url = "https://example.com/v1"',
                        'env_key = "EXISTING_API_KEY"',
                        'wire_api = "responses"',
                        "",
                    )
                ),
                encoding="utf-8",
            )

            full_manifest = SyncManifest.create(
                full_runtime_config,
                SyncRequest.create(full_runtime_config.frontend_targets, dry_run=False),
            )
            apply_sync_manifest(project_root, full_manifest)

            unmanaged_codex_skill_dir = project_root / ".codex" / "skills" / "custom-local"
            unmanaged_codex_skill_dir.mkdir(parents=True, exist_ok=True)
            (unmanaged_codex_skill_dir / "SKILL.md").write_text(
                "name: custom-local\n",
                encoding="utf-8",
            )

            opencode_only_manifest = SyncManifest.create(
                opencode_only_runtime_config,
                SyncRequest.create(opencode_only_runtime_config.frontend_targets, dry_run=False),
            )
            result = apply_sync_manifest(project_root, opencode_only_manifest)

            cleaned_codex_payload = tomllib.loads(codex_path.read_text(encoding="utf-8"))
            self.assertEqual(cleaned_codex_payload["model_reasoning_effort"], "high")
            self.assertNotIn("profile", cleaned_codex_payload)
            self.assertEqual(cleaned_codex_payload["profiles"], {"fast": {"model": "gpt-5.4"}})
            self.assertEqual(
                cleaned_codex_payload["model_providers"]["existing"]["base_url"],
                "https://example.com/v1",
            )
            self.assertNotIn("aistackd", cleaned_codex_payload["model_providers"])
            self.assertFalse((project_root / ".codex" / "skills" / "find-skills" / "SKILL.md").exists())
            self.assertFalse((project_root / ".codex" / "tools" / "runtime-status.py").exists())
            self.assertFalse((project_root / ".codex" / "tools" / "responses-smoke.py").exists())
            self.assertFalse((project_root / ".codex" / "tools" / "runtime-wait.py").exists())
            self.assertFalse((project_root / ".codex" / "tools" / "frontend-smoke.py").exists())
            self.assertFalse((project_root / ".codex" / "tools" / "tool-call-demo.py").exists())
            self.assertTrue((project_root / ".codex" / "skills" / "custom-local" / "SKILL.md").exists())
            self.assertIn(str(codex_path), result.removed_paths)

            ownership_manifest = SyncOwnershipManifest.load(project_root)
            self.assertIsNotNone(ownership_manifest)
            assert ownership_manifest is not None
            self.assertEqual(tuple(target.frontend for target in ownership_manifest.targets), ("opencode",))

    def test_sync_write_preserves_unmanaged_project_local_skills_and_provenance(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000",
            api_key_env="AISTACKD_API_KEY",
            model="local-model",
        )
        runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode"))
        manifest = SyncManifest.create(
            runtime_config,
            SyncRequest.create(runtime_config.frontend_targets, dry_run=False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            unmanaged_skill_dir = project_root / ".agents" / "skills" / "project-custom"
            unmanaged_skill_dir.mkdir(parents=True, exist_ok=True)
            (unmanaged_skill_dir / "SKILL.md").write_text("name: project-custom\n", encoding="utf-8")
            (unmanaged_skill_dir / PROJECT_LOCAL_SKILL_PROVENANCE_FILE_NAME).write_text(
                json.dumps(
                    {
                        "schema_version": "v1alpha1",
                        "source_type": "skills.sh",
                        "source": "example/project-custom",
                        "installed_via": "manual",
                        "snapshot_date": "2026-03-12",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            first_result = apply_sync_manifest(project_root, manifest)
            second_result = apply_sync_manifest(project_root, manifest)

            self.assertTrue((unmanaged_skill_dir / "SKILL.md").exists())
            self.assertTrue((unmanaged_skill_dir / PROJECT_LOCAL_SKILL_PROVENANCE_FILE_NAME).exists())
            self.assertNotIn(str(unmanaged_skill_dir / "SKILL.md"), first_result.written_paths)
            self.assertNotIn(str(unmanaged_skill_dir / "SKILL.md"), second_result.written_paths)

    def test_sync_write_prunes_openhands_config_and_preserves_unmanaged_microagents(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000",
            api_key_env="AISTACKD_API_KEY",
            model="local-model",
        )
        full_runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode", "openhands"))
        reduced_runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode"))

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            full_manifest = SyncManifest.create(
                full_runtime_config,
                SyncRequest.create(full_runtime_config.frontend_targets, dry_run=False),
            )
            apply_sync_manifest(project_root, full_manifest)

            unmanaged_microagent = project_root / ".openhands" / "microagents" / "custom-local.md"
            unmanaged_microagent.parent.mkdir(parents=True, exist_ok=True)
            unmanaged_microagent.write_text("# Custom Local\n", encoding="utf-8")

            manifest = SyncManifest.create(
                reduced_runtime_config,
                SyncRequest.create(reduced_runtime_config.frontend_targets, dry_run=False),
            )
            result = apply_sync_manifest(project_root, manifest)

            self.assertFalse((project_root / ".openhands" / "config.toml").exists())
            self.assertFalse((project_root / ".openhands" / "microagents" / "find-skills.md").exists())
            self.assertTrue(unmanaged_microagent.exists())
            self.assertIn(str(project_root / ".openhands" / "config.toml"), result.removed_paths)

    def test_sync_write_renders_executable_tools_with_runtime_defaults(self) -> None:
        profile = Profile(
            name="local",
            base_url="http://127.0.0.1:8000",
            api_key_env="AISTACKD_API_KEY",
            model="local-model",
        )
        runtime_config = RuntimeConfig.for_client(profile, ("codex", "opencode"))
        manifest = SyncManifest.create(
            runtime_config,
            SyncRequest.create(runtime_config.frontend_targets, dry_run=False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            apply_sync_manifest(project_root, manifest)

            codex_tool = project_root / ".codex" / "tools" / "runtime-status.py"
            opencode_tool = project_root / ".opencode" / "tools" / "model-admin.py"
            codex_smoke_tool = project_root / ".codex" / "tools" / "responses-smoke.py"
            opencode_wait_tool = project_root / ".opencode" / "tools" / "runtime-wait.py"
            codex_frontend_smoke_tool = project_root / ".codex" / "tools" / "frontend-smoke.py"
            opencode_tool_call_demo = project_root / ".opencode" / "tools" / "tool-call-demo.py"

            self.assertTrue(codex_tool.exists())
            self.assertTrue(opencode_tool.exists())
            self.assertTrue(codex_smoke_tool.exists())
            self.assertTrue(opencode_wait_tool.exists())
            self.assertTrue(codex_frontend_smoke_tool.exists())
            self.assertTrue(opencode_tool_call_demo.exists())
            self.assertTrue(os.access(codex_tool, os.X_OK))
            self.assertTrue(os.access(opencode_tool, os.X_OK))
            self.assertTrue(os.access(codex_smoke_tool, os.X_OK))
            self.assertTrue(os.access(opencode_wait_tool, os.X_OK))
            self.assertTrue(os.access(codex_frontend_smoke_tool, os.X_OK))
            self.assertTrue(os.access(opencode_tool_call_demo, os.X_OK))
            self.assertIn('DEFAULT_BASE_URL = "http://127.0.0.1:8000"', codex_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_API_KEY_ENV = "AISTACKD_API_KEY"', opencode_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_BASE_URL = "http://127.0.0.1:8000"', codex_smoke_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_API_KEY_ENV = "AISTACKD_API_KEY"', opencode_wait_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_ACTIVE_PROFILE = "local"', codex_frontend_smoke_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_MODEL = "local-model"', opencode_tool_call_demo.read_text(encoding="utf-8"))
