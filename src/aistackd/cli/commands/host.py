"""Host command scaffold."""

from __future__ import annotations

import argparse

from aistackd.cli.commands.common import render_placeholder
from aistackd.models.sources import BACKEND_ACQUISITION_POLICY, PRIMARY_BACKEND
from aistackd.runtime.modes import all_runtime_modes


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``host`` command."""
    parser = subparsers.add_parser("host", help="host runtime command surface")
    parser.set_defaults(handler=handle)


def handle(_: argparse.Namespace) -> int:
    """Handle the ``host`` scaffold command."""
    return render_placeholder(
        command_name="host",
        phase="phase_2_runtime",
        summary="host runtime behavior is not implemented yet; this command reserves the public surface.",
        details=(
            f"backend: {PRIMARY_BACKEND}",
            f"backend_policy: {BACKEND_ACQUISITION_POLICY}",
            f"supported_runtime_modes: {', '.join(all_runtime_modes())}",
        ),
    )
