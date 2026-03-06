"""CLI tests for the Phase 0 scaffold."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

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

    def test_profiles_reports_reserved_state_locations(self) -> None:
        exit_code, stdout, stderr = invoke(["profiles"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn(".aistackd/profiles", stdout)
        self.assertIn(".aistackd/active_profile", stdout)
