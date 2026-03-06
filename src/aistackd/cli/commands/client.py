"""Client command scaffold."""

from __future__ import annotations

import argparse

from aistackd.cli.commands.common import render_placeholder
from aistackd.frontends.catalog import SUPPORTED_FRONTENDS


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``client`` command."""
    parser = subparsers.add_parser("client", help="client runtime command surface")
    parser.set_defaults(handler=handle)


def handle(_: argparse.Namespace) -> int:
    """Handle the ``client`` scaffold command."""
    return render_placeholder(
        command_name="client",
        phase="phase_3_runtime",
        summary="client runtime behavior is not implemented yet; this command reserves the public surface.",
        details=(f"frontend_targets: {', '.join(SUPPORTED_FRONTENDS)}",),
    )
