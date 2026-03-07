"""Client command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.frontends.catalog import SUPPORTED_FRONTENDS
from aistackd.runtime.config import RuntimeConfig
from aistackd.state.profiles import ProfileStore, ProfileStoreError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``client`` command."""
    parser = subparsers.add_parser("client", help="show the active client runtime config")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root containing the .aistackd state directory",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Render the active client runtime config."""
    try:
        profile = ProfileStore(args.project_root).get_active_profile()
        if profile is None:
            return _exit_with_error("no active profile is set")
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    runtime_config = RuntimeConfig.for_client(profile, SUPPORTED_FRONTENDS)
    if args.format == "json":
        print(json.dumps(runtime_config.to_dict(), indent=2))
        return 0

    print("client runtime config")
    print(f"active_profile: {runtime_config.active_profile}")
    print(f"mode: {runtime_config.mode}")
    print(f"base_url: {runtime_config.base_url}")
    print(f"responses_base_url: {runtime_config.responses_base_url}")
    print(f"api_key_env: {runtime_config.api_key_env}")
    print(f"model: {runtime_config.model}")
    print(f"frontend_targets: {', '.join(runtime_config.frontend_targets)}")
    if runtime_config.profile_role_hint is not None:
        print(f"profile_role_hint: {runtime_config.profile_role_hint}")
    return 0


def _exit_with_error(message: str) -> int:
    """Print a client command error and return a failing exit code."""
    print(message, file=sys.stderr)
    return 1
