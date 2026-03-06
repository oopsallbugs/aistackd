"""Doctor command scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aistackd.state.layout import ProjectLayout


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``doctor`` command."""
    parser = subparsers.add_parser("doctor", help="inspect scaffold health and layout")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root to inspect",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Handle the ``doctor`` command."""
    layout = ProjectLayout.discover(args.project_root)
    if args.format == "json":
        print(json.dumps(layout.as_dict(), indent=2))
    else:
        print(layout.format_text())
    return 0
