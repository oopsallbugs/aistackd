"""Profiles command scaffold."""

from __future__ import annotations

import argparse
from pathlib import Path

from aistackd.cli.commands.common import render_placeholder
from aistackd.state.profiles import ProfileStatePaths


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``profiles`` command."""
    parser = subparsers.add_parser("profiles", help="profile management command surface")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root to inspect for state paths",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Handle the ``profiles`` scaffold command."""
    paths = ProfileStatePaths.from_project_root(args.project_root)
    return render_placeholder(
        command_name="profiles",
        phase="phase_1_contracts",
        summary="profile schema and persistence are not implemented yet; this command exposes the intended state locations.",
        project_root=args.project_root,
        details=(
            f"profile_store: {paths.profiles_dir}",
            f"active_profile_file: {paths.active_profile_path}",
        ),
    )
