"""Frontend sync command scaffold."""

from __future__ import annotations

import argparse

from aistackd.cli.commands.common import render_placeholder
from aistackd.frontends.catalog import SUPPORTED_FRONTENDS, normalize_frontend_targets
from aistackd.skills.catalog import PLANNED_BASELINE_SKILLS


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``sync`` command."""
    parser = subparsers.add_parser("sync", help="frontend sync command surface")
    parser.add_argument(
        "--target",
        action="append",
        choices=SUPPORTED_FRONTENDS,
        dest="targets",
        help="target frontend to sync; defaults to all supported frontends",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview sync behavior without writing any config",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Handle the ``sync`` scaffold command."""
    targets = normalize_frontend_targets(args.targets)
    return render_placeholder(
        command_name="sync",
        phase="phase_4_frontend_sync",
        summary="frontend sync is not implemented yet; this command reserves the provider and baseline content sync surface.",
        details=(
            f"targets: {', '.join(targets)}",
            f"dry_run: {'enabled' if args.dry_run else 'disabled'}",
            f"planned_baseline_skills: {', '.join(PLANNED_BASELINE_SKILLS)}",
        ),
    )
