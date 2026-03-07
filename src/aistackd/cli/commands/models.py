"""Models command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.state.profiles import Profile, ProfileStore, ProfileStoreError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``models`` command."""
    parser = subparsers.add_parser("models", help="inspect or update profile-bound model selection")
    _add_common_arguments(parser)
    parser.set_defaults(handler=handle_show)

    command_parsers = parser.add_subparsers(dest="models_command", metavar="models_command")

    list_parser = command_parsers.add_parser("list", help="list configured profile models")
    _add_common_arguments(list_parser)
    list_parser.set_defaults(handler=handle_list)

    show_parser = command_parsers.add_parser("show", help="show a model for one profile")
    _add_common_arguments(show_parser)
    show_parser.add_argument("name", nargs="?", help="profile name to inspect; defaults to the active profile")
    show_parser.set_defaults(handler=handle_show)

    set_parser = command_parsers.add_parser("set", help="set the model for a profile")
    _add_common_arguments(set_parser)
    set_parser.add_argument("model", help="model identifier to store on the profile")
    set_parser.add_argument(
        "--profile",
        dest="profile_name",
        help="profile name to update; defaults to the active profile",
    )
    set_parser.set_defaults(handler=handle_set)


def handle_list(args: argparse.Namespace) -> int:
    """List models for all configured profiles."""
    try:
        store = ProfileStore(args.project_root)
        profiles = store.list_profiles()
        active_profile_name = store.get_active_profile_name()
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        payload = {
            "profiles": [_model_payload(profile, active_profile_name) for profile in profiles],
            "active_profile": active_profile_name,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not profiles:
        print("no profiles configured")
        return 0

    print(f"profile_models: {len(profiles)}")
    for profile in profiles:
        active_marker = "*" if profile.name == active_profile_name else " "
        print(f"{active_marker} {profile.name}: {profile.model}")
    return 0


def handle_show(args: argparse.Namespace) -> int:
    """Show the model for one profile."""
    try:
        store = ProfileStore(args.project_root)
        active_profile_name = store.get_active_profile_name()
        profile_name = getattr(args, "name", None)
        profile = store.load_profile(profile_name) if profile_name else store.get_active_profile()
        if profile is None:
            return _exit_with_error("no active profile is set")
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    payload = _model_payload(profile, active_profile_name)
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"profile: {profile.name}")
    print(f"model: {profile.model}")
    print(f"active: {'yes' if payload['active'] else 'no'}")
    print(f"base_url: {profile.base_url}")
    return 0


def handle_set(args: argparse.Namespace) -> int:
    """Update the model selection for one profile."""
    try:
        store = ProfileStore(args.project_root)
        profile_name = args.profile_name or store.get_active_profile_name()
        if profile_name is None:
            return _exit_with_error("no active profile is set")
        existing_profile = store.load_profile(profile_name)
        updated_profile = existing_profile.with_model(args.model)
        store.save_profile(updated_profile)
        active_profile_name = store.get_active_profile_name()
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    payload = _model_payload(updated_profile, active_profile_name)
    if args.format == "json":
        print(json.dumps({"action": "updated", "profile": payload}, indent=2))
        return 0

    print(f"updated model for profile '{updated_profile.name}'")
    print(f"model: {updated_profile.model}")
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared CLI arguments."""
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


def _model_payload(profile: Profile, active_profile_name: str | None) -> dict[str, object]:
    """Build a stable JSON payload for one profile model."""
    return {
        "profile": profile.name,
        "model": profile.model,
        "active": profile.name == active_profile_name,
        "base_url": profile.base_url,
        "schema_version": profile.schema_version,
    }


def _exit_with_error(message: str) -> int:
    """Print an error message and return a failing exit code."""
    print(message, file=sys.stderr)
    return 1
