"""Layout tests for the Phase 0 scaffold."""

from __future__ import annotations

import unittest
from pathlib import Path

from aistackd.state.host import HOST_DIRECTORY_NAME, HostStatePaths
from aistackd.state.layout import ProjectLayout
from aistackd.state.profiles import ACTIVE_PROFILE_FILE_NAME, ProfileStatePaths, RUNTIME_STATE_DIRECTORY_NAME


class LayoutTests(unittest.TestCase):
    def test_project_layout_detects_expected_scaffold_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        layout = ProjectLayout.discover(repo_root)

        self.assertEqual(Path(layout.project_root), repo_root)
        self.assertIn("host", layout.command_groups)
        self.assertIn("sync", layout.command_groups)
        self.assertEqual(layout.runtime_backend, "llama.cpp")

        scaffold_checks = {entry.label: entry.exists for entry in layout.scaffold_paths}
        self.assertTrue(scaffold_checks["package_root"])
        self.assertTrue(scaffold_checks["tests"])
        self.assertTrue(scaffold_checks["shared_skills"])
        self.assertTrue(scaffold_checks["shared_tools"])

        reserved_checks = {entry.label: entry.path for entry in layout.reserved_paths}
        self.assertIn("host_state_dir", reserved_checks)
        self.assertIn("backend_installation_file", reserved_checks)
        self.assertIn("managed_backends_dir", reserved_checks)
        self.assertIn("managed_models_dir", reserved_checks)
        self.assertIn("installed_models_file", reserved_checks)

    def test_profile_state_paths_follow_canonical_names(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        paths = ProfileStatePaths.from_project_root(repo_root)

        self.assertEqual(paths.runtime_state_root.name, RUNTIME_STATE_DIRECTORY_NAME)
        self.assertEqual(paths.active_profile_path.name, ACTIVE_PROFILE_FILE_NAME)
        self.assertEqual(paths.profiles_dir.parent, paths.runtime_state_root)

    def test_host_state_paths_follow_canonical_names(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        paths = HostStatePaths.from_project_root(repo_root)

        self.assertEqual(paths.runtime_state_root.name, RUNTIME_STATE_DIRECTORY_NAME)
        self.assertEqual(paths.host_dir.name, HOST_DIRECTORY_NAME)
        self.assertEqual(paths.host_dir.parent, paths.runtime_state_root)
