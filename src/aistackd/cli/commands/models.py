"""Models command scaffold."""

from __future__ import annotations

import argparse

from aistackd.cli.commands.common import render_placeholder
from aistackd.models.sources import (
    BACKEND_ACQUISITION_POLICY,
    FALLBACK_MODEL_SOURCE,
    MODEL_SOURCE_POLICY,
    PRIMARY_MODEL_SOURCE,
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``models`` command."""
    parser = subparsers.add_parser("models", help="model management command surface")
    parser.set_defaults(handler=handle)


def handle(_: argparse.Namespace) -> int:
    """Handle the ``models`` scaffold command."""
    return render_placeholder(
        command_name="models",
        phase="phase_2_runtime",
        summary="model recommendation, acquisition, and activation are not implemented yet.",
        details=(
            f"model_source_policy: {MODEL_SOURCE_POLICY}",
            f"primary_model_source: {PRIMARY_MODEL_SOURCE}",
            f"fallback_model_source: {FALLBACK_MODEL_SOURCE}",
            f"backend_policy: {BACKEND_ACQUISITION_POLICY}",
        ),
    )
