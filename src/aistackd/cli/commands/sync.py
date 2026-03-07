"""Frontend sync command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.frontends.catalog import SUPPORTED_FRONTENDS
from aistackd.frontends.sync import SyncManifest, SyncRequest
from aistackd.runtime.config import RuntimeConfig
from aistackd.state.profiles import ProfileStore, ProfileStoreError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``sync`` command."""
    parser = subparsers.add_parser("sync", help="preview frontend sync from the active profile")
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
        help="explicitly request preview mode; write mode is not implemented yet",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Build and print a sync manifest preview from the active profile."""
    try:
        profile = ProfileStore(args.project_root).get_active_profile()
        if profile is None:
            return _exit_with_error("no active profile is set")
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    runtime_config = RuntimeConfig.for_client(profile, args.targets)
    request = SyncRequest.create(runtime_config.frontend_targets, dry_run=True)
    manifest = SyncManifest.create(runtime_config, request)

    if args.format == "json":
        print(json.dumps(manifest.to_dict(), indent=2))
        return 0

    print("sync preview")
    print(f"active_profile: {manifest.active_profile}")
    print(f"mode: {manifest.mode}")
    print(f"dry_run: {'enabled' if manifest.dry_run else 'disabled'}")
    print("write_mode: not_implemented")
    for plan in manifest.targets:
        print(f"frontend: {plan.frontend}")
        print(f"provider_base_url: {plan.provider_base_url}")
        print(f"api_key_env: {plan.api_key_env}")
        print(f"baseline_skills: {', '.join(plan.baseline_skills)}")
        print(
            f"baseline_tools: {', '.join(plan.baseline_tools) if plan.baseline_tools else 'none'}"
        )
    return 0


def _exit_with_error(message: str) -> int:
    """Print a sync command error and return a failing exit code."""
    print(message, file=sys.stderr)
    return 1
