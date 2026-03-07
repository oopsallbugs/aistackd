"""CLI tests for scaffold and contract slices."""

from __future__ import annotations

import io
import json
import os
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from aistackd.cli.main import build_parser, main
from aistackd.state.layout import COMMAND_GROUPS


def invoke(argv: list[str]) -> tuple[int, str, str]:
    """Invoke the CLI entrypoint and capture stdio."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class CLITests(unittest.TestCase):
    def test_help_lists_documented_command_groups(self) -> None:
        help_text = build_parser().format_help()
        for command_name in COMMAND_GROUPS:
            self.assertIn(command_name, help_text)

    def test_doctor_reports_scaffold_as_json(self) -> None:
        exit_code, stdout, stderr = invoke(["doctor", "--format", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")

        payload = json.loads(stdout)
        self.assertEqual(payload["command_groups"], list(COMMAND_GROUPS))

        scaffold_checks = {entry["label"]: entry["exists"] for entry in payload["scaffold_paths"]}
        self.assertTrue(scaffold_checks["package_root"])
        self.assertTrue(scaffold_checks["ci_workflow"])
        self.assertTrue(scaffold_checks["shared_skills"])
        self.assertTrue(scaffold_checks["shared_tools"])

    def test_profiles_add_list_show_and_activate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--role-hint",
                    "host",
                    "--activate",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("created profile 'local'", stdout)
            self.assertIn("active_profile: local", stdout)

            exit_code, stdout, stderr = invoke(["profiles", "list", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("* local: http://127.0.0.1:8000", stdout)
            self.assertIn("api_key_env=AISTACKD_API_KEY", stdout)
            self.assertIn("model=local-model", stdout)

            exit_code, stdout, stderr = invoke(["profiles", "show", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("name: local", stdout)
            self.assertIn("active: yes", stdout)
            self.assertIn("model: local-model", stdout)
            self.assertIn("role_hint: host", stdout)

    def test_profiles_validate_reports_missing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = invoke(
                [
                    "profiles",
                    "add",
                    "remote-host",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://10.0.0.50:8080",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("AISTACKD_REMOTE_API_KEY", None)
                exit_code, stdout, stderr = invoke(["profiles", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stderr, "")
            self.assertIn("profile: remote-host", stdout)
            self.assertIn("status: invalid", stdout)
            self.assertIn("readiness_error: api key environment variable 'AISTACKD_REMOTE_API_KEY' is not set or empty", stdout)

    def test_profiles_validate_succeeds_when_api_key_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                exit_code, stdout, stderr = invoke(["profiles", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("profile: local", stdout)
            self.assertIn("status: ok", stdout)

    def test_client_reports_active_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--role-hint",
                    "host",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(["client", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("client runtime config", stdout)
            self.assertIn("active_profile: local", stdout)
            self.assertIn("responses_base_url: http://127.0.0.1:8000/v1", stdout)
            self.assertIn("model: local-model", stdout)
            self.assertIn("frontend_targets: codex, opencode", stdout)

    def test_models_show_list_and_set_active_profile_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(["models", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("profile: local", stdout)
            self.assertIn("model: local-model", stdout)

            exit_code, stdout, stderr = invoke(["models", "list", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("* local: local-model", stdout)

            exit_code, stdout, stderr = invoke(
                ["models", "set", "refined-model", "--project-root", tmpdir, "--format", "json"]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "updated")
            self.assertEqual(payload["profile"]["profile"], "local")
            self.assertEqual(payload["profile"]["model"], "refined-model")

            exit_code, stdout, stderr = invoke(["models", "--project-root", tmpdir, "--format", "json"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["profile"], "local")
            self.assertEqual(payload["model"], "refined-model")
            self.assertTrue(payload["active"])

    def test_models_search_install_activate_and_host_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = invoke(["models", "recommend", "--project-root", tmpdir, "--format", "json"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertGreaterEqual(len(payload["models"]), 2)
            self.assertEqual(payload["models"][0]["source"], "llmfit")

            exit_code, stdout, stderr = invoke(
                [
                    "models",
                    "install",
                    "qwen2.5-coder-7b-instruct-q4-k-m",
                    "--project-root",
                    tmpdir,
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "installed")
            self.assertEqual(payload["model"]["source"], "llmfit")
            self.assertIsNone(payload["active_model"])

            exit_code, stdout, stderr = invoke(["models", "installed", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("installed_models: 1", stdout)
            self.assertIn("qwen2.5-coder-7b-instruct-q4-k-m: source=llmfit", stdout)

            exit_code, stdout, stderr = invoke(
                [
                    "models",
                    "activate",
                    "qwen2.5-coder-7b-instruct-q4-k-m",
                    "--project-root",
                    tmpdir,
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "activated")
            self.assertEqual(payload["runtime"]["active_model"], "qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertEqual(payload["runtime"]["activation_state"], "ready")

            exit_code, stdout, stderr = invoke(["host", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("host runtime state", stdout)
            self.assertIn("active_model: qwen2.5-coder-7b-instruct-q4-k-m", stdout)
            self.assertIn("installed_models: 1", stdout)

            exit_code, stdout, stderr = invoke(["host", "validate", "--project-root", tmpdir, "--format", "json"])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertIn(
                "api key environment variable 'AISTACKD_API_KEY' is not set or empty",
                payload["errors"],
            )

            with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                exit_code, stdout, stderr = invoke(["host", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("host validation", stdout)
            self.assertIn("status: ok", stdout)
            self.assertIn("base_url: http://127.0.0.1:8000", stdout)

            with patch("aistackd.cli.commands.host.serve_control_plane") as serve_mock:
                with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                    exit_code, stdout, stderr = invoke(["host", "serve", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("control plane serving", stdout)
            self.assertIn("active_model: qwen2.5-coder-7b-instruct-q4-k-m", stdout)
            serve_mock.assert_called_once()

    def test_sync_preview_uses_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(
                ["sync", "--project-root", tmpdir, "--target", "codex", "--format", "json"]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")

            payload = json.loads(stdout)
            self.assertEqual(payload["active_profile"], "local")
            self.assertEqual(payload["mode"], "client")
            self.assertTrue(payload["dry_run"])
            self.assertEqual(len(payload["targets"]), 1)
            self.assertEqual(payload["targets"][0]["frontend"], "codex")
            self.assertEqual(payload["targets"][0]["provider_base_url"], "http://127.0.0.1:8000/v1")
            self.assertEqual(payload["targets"][0]["provider_config_path"], ".codex/config.toml")
            self.assertEqual(payload["targets"][0]["activation_mode"], "project_local")
            self.assertEqual(
                payload["targets"][0]["provider_payload"]["profiles"]["aistackd"]["model"],
                "local-model",
            )

            exit_code, stdout, stderr = invoke(["sync", "--project-root", tmpdir, "--target", "codex"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("change_summary: create=2", stdout)
            self.assertIn("change: create frontend=codex kind=provider_config path=.codex/config.toml", stdout)

    def test_sync_requires_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = invoke(["sync", "--project-root", tmpdir])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("no active profile is set", stderr)

    def test_sync_write_creates_managed_files_and_ownership_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            opencode_path = Path(tmpdir) / "opencode.json"
            opencode_path.write_text(
                json.dumps(
                    {
                        "custom": {"keep": True},
                        "provider": {"existing": {"name": "keep"}},
                        "model": "existing/default",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(["sync", "--project-root", tmpdir, "--write"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("sync write", stdout)
            self.assertIn("ownership_manifest:", stdout)

            opencode_payload = json.loads(opencode_path.read_text(encoding="utf-8"))
            self.assertEqual(opencode_payload["custom"], {"keep": True})
            self.assertIn("existing", opencode_payload["provider"])
            self.assertIn("aistackd", opencode_payload["provider"])
            self.assertEqual(opencode_payload["model"], "aistackd/local-model")
            self.assertEqual(
                opencode_payload["provider"]["aistackd"]["models"]["local-model"]["name"],
                "local-model",
            )

            codex_payload = tomllib.loads(
                (Path(tmpdir) / ".codex" / "config.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(codex_payload["profile"], "aistackd")
            self.assertEqual(
                codex_payload["profiles"]["aistackd"]["model_provider"],
                "aistackd",
            )
            self.assertEqual(codex_payload["profiles"]["aistackd"]["model"], "local-model")
            self.assertEqual(
                codex_payload["model_providers"]["aistackd"]["base_url"],
                "http://127.0.0.1:8000/v1",
            )
            self.assertEqual(
                codex_payload["model_providers"]["aistackd"]["env_key"],
                "AISTACKD_API_KEY",
            )

            opencode_skill = Path(tmpdir) / ".opencode" / "skills" / "find-skills" / "SKILL.md"
            codex_skill = Path(tmpdir) / ".codex" / "skills" / "find-skills" / "SKILL.md"
            self.assertTrue(opencode_skill.exists())
            self.assertTrue(codex_skill.exists())
            self.assertIn("name: find-skills", opencode_skill.read_text(encoding="utf-8"))

            ownership_manifest_path = (
                Path(tmpdir) / ".aistackd" / "sync" / "ownership_manifest.json"
            )
            ownership_payload = json.loads(ownership_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(ownership_payload["active_profile"], "local")
            self.assertEqual(len(ownership_payload["targets"]), 2)
