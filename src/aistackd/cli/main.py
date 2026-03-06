"""Command-line entrypoint for aistackd."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from aistackd.cli.commands import COMMAND_MODULES


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="aistackd",
        description="Phase 0 scaffold for the aistackd host/client AI stack.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for module in COMMAND_MODULES:
        module.register(subparsers)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected command handler."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)

    if handler is None:
        parser.print_help()
        return 0

    result = handler(args)
    return 0 if result is None else int(result)


def run() -> None:
    """Console-script wrapper."""
    raise SystemExit(main())
