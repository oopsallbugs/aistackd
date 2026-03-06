"""CLI tests for the Phase 0 scaffold."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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

    def test_sync_accepts_target_selection(self) -> None:
        exit_code, stdout, stderr = invoke(["sync", "--target", "codex", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("targets: codex", stdout)
        self.assertIn("dry_run: enabled", stdout)

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

            exit_code, stdout, stderr = invoke(["profiles", "show", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("name: local", stdout)
            self.assertIn("active: yes", stdout)
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
                    "--activate",
                ]
            )

            with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                exit_code, stdout, stderr = invoke(["profiles", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("profile: local", stdout)
            self.assertIn("status: ok", stdout)
