"""Frontend-oriented CLI aliases."""

from __future__ import annotations

import argparse
from pathlib import Path

from aistackd.cli.commands import doctor as doctor_command
from aistackd.cli.commands import sync as sync_command
from aistackd.frontends.catalog import SUPPORTED_FRONTENDS


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``frontend`` command group."""
    parser = subparsers.add_parser("frontend", help="frontend workflow aliases for sync and readiness")
    command_parsers = parser.add_subparsers(dest="frontend_command", metavar="frontend_command")

    sync_parser = command_parsers.add_parser("sync", help="alias for 'sync'")
    sync_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root containing the .aistackd state directory",
    )
    sync_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    sync_parser.add_argument(
        "--target",
        action="append",
        choices=SUPPORTED_FRONTENDS,
        dest="targets",
        help="target frontend to sync; defaults to all supported frontends",
    )
    mode_group = sync_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="preview sync behavior without writing files; this is the default",
    )
    mode_group.add_argument(
        "--write",
        action="store_true",
        help="write managed frontend config, baseline skills, and ownership state",
    )
    sync_parser.set_defaults(handler=sync_command.handle)

    ready_parser = command_parsers.add_parser("ready", help="alias for 'doctor ready'")
    ready_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root to inspect",
    )
    ready_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    ready_parser.add_argument(
        "--frontend",
        choices=SUPPORTED_FRONTENDS,
        default=doctor_command.DEFAULT_READY_FRONTEND,
        help=f"frontend target to validate (default: {doctor_command.DEFAULT_READY_FRONTEND})",
    )
    ready_parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="skip the final /v1/responses smoke request",
    )
    ready_parser.add_argument(
        "--timeout",
        type=int,
        default=doctor_command.DEFAULT_READY_TIMEOUT_SECONDS,
        help=(
            "remote validation and smoke timeout in seconds "
            f"(default: {doctor_command.DEFAULT_READY_TIMEOUT_SECONDS})"
        ),
    )
    ready_parser.set_defaults(handler=doctor_command.handle_ready)
