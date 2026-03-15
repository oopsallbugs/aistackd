"""Profiles command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.state.profiles import (
    ALLOWED_PROFILE_ROLE_HINTS,
    Profile,
    ProfileStore,
    ProfileStoreError,
    ProfileValidationResult,
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``profiles`` command."""
    parser = subparsers.add_parser("profiles", help="profile management commands")
    _add_common_arguments(parser)
    parser.set_defaults(handler=handle_list)

    command_parsers = parser.add_subparsers(dest="profiles_command", metavar="profiles_command")

    list_parser = command_parsers.add_parser("list", help="list configured profiles")
    _add_common_arguments(list_parser)
    list_parser.set_defaults(handler=handle_list)

    show_parser = command_parsers.add_parser("show", help="show a profile or the active profile")
    _add_common_arguments(show_parser)
    show_parser.add_argument("name", nargs="?", help="profile name to display; defaults to the active profile")
    show_parser.set_defaults(handler=handle_show)

    add_parser = command_parsers.add_parser("add", help="create or update a profile")
    _add_common_arguments(add_parser)
    add_parser.add_argument("name", help="profile name")
    add_parser.add_argument("--base-url", required=True, help="backend base URL for the profile")
    add_parser.add_argument("--api-key-env", required=True, help="environment variable containing the API key")
    add_parser.add_argument("--model", required=True, help="active model for the profile")
    add_parser.add_argument(
        "--role-hint",
        choices=ALLOWED_PROFILE_ROLE_HINTS,
        help="optional role hint for the backend target",
    )
    add_parser.add_argument("--description", help="optional description for operators")
    add_parser.add_argument("--activate", action="store_true", help="set the profile as active after saving")
    add_parser.set_defaults(handler=handle_add)

    activate_parser = command_parsers.add_parser("activate", help="set the active profile")
    _add_common_arguments(activate_parser)
    activate_parser.add_argument("name", help="profile name to activate")
    activate_parser.set_defaults(handler=handle_activate)

    use_parser = command_parsers.add_parser("use", help="alias for 'profiles activate'")
    _add_common_arguments(use_parser)
    use_parser.add_argument("name", help="profile name to activate")
    use_parser.set_defaults(handler=handle_activate)

    validate_parser = command_parsers.add_parser("validate", help="validate one or more profiles")
    _add_common_arguments(validate_parser)
    validate_parser.add_argument("name", nargs="?", help="profile name to validate")
    validate_parser.add_argument("--all", action="store_true", help="validate all configured profiles")
    validate_parser.set_defaults(handler=handle_validate)


def handle_list(args: argparse.Namespace) -> int:
    """List configured profiles."""
    try:
        store = ProfileStore(args.project_root)
        profiles = store.list_profiles()
        active_profile_name = store.get_active_profile_name()
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        payload = {
            "profiles": [_profile_payload(profile, active_profile_name) for profile in profiles],
            "active_profile": active_profile_name,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not profiles:
        print("no profiles configured")
        return 0

    print(f"profiles: {len(profiles)}")
    for profile in profiles:
        active_marker = "*" if profile.name == active_profile_name else " "
        line = (
            f"{active_marker} {profile.name}: {profile.base_url} "
            f"api_key_env={profile.api_key_env} model={profile.model}"
        )
        if profile.role_hint is not None:
            line += f" role_hint={profile.role_hint}"
        print(line)

    return 0


def handle_show(args: argparse.Namespace) -> int:
    """Show a specific profile or the active profile."""
    try:
        store = ProfileStore(args.project_root)
        active_profile_name = store.get_active_profile_name()
        profile = store.load_profile(args.name) if args.name else store.get_active_profile()
        if profile is None:
            return _exit_with_error("no active profile is set")
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    payload = _profile_payload(profile, active_profile_name)
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"name: {profile.name}")
    print(f"base_url: {profile.base_url}")
    print(f"api_key_env: {profile.api_key_env}")
    print(f"model: {profile.model}")
    print(f"schema_version: {profile.schema_version}")
    print(f"active: {'yes' if payload['active'] else 'no'}")
    if profile.role_hint is not None:
        print(f"role_hint: {profile.role_hint}")
    if profile.description is not None:
        print(f"description: {profile.description}")
    return 0


def handle_add(args: argparse.Namespace) -> int:
    """Create or update a profile."""
    profile = Profile(
        name=args.name,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        model=args.model,
        role_hint=args.role_hint,
        description=args.description,
    )

    try:
        store = ProfileStore(args.project_root)
        created = store.save_profile(profile)
        active_profile_name = store.get_active_profile_name()
        if args.activate:
            active_profile_name = store.activate_profile(profile.name).name
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    action = "created" if created else "updated"
    payload = {
        "action": action,
        "profile": _profile_payload(profile.normalized(), active_profile_name),
    }

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"{action} profile '{profile.name}'")
    if args.activate:
        print(f"active_profile: {profile.name}")
    return 0


def handle_activate(args: argparse.Namespace) -> int:
    """Set the active profile pointer."""
    try:
        store = ProfileStore(args.project_root)
        profile = store.activate_profile(args.name)
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    payload = _profile_payload(profile, profile.name)
    if args.format == "json":
        print(json.dumps({"active_profile": profile.name, "profile": payload}, indent=2))
        return 0

    print(f"active_profile: {profile.name}")
    print(f"base_url: {profile.base_url}")
    return 0


def handle_validate(args: argparse.Namespace) -> int:
    """Validate one or more profiles."""
    try:
        store = ProfileStore(args.project_root)
        target_names = _resolve_validation_targets(store, args)
        results = tuple(store.validate_profile(profile_name) for profile_name in target_names)
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps({"results": [result.as_dict() for result in results]}, indent=2))
    else:
        _render_validation_results(results)

    return 0 if all(result.ok for result in results) else 1


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


def _profile_payload(profile: Profile, active_profile_name: str | None) -> dict[str, object]:
    """Build a stable JSON payload for a profile."""
    payload = profile.to_dict()
    payload["active"] = profile.name == active_profile_name
    return payload


def _resolve_validation_targets(store: ProfileStore, args: argparse.Namespace) -> tuple[str, ...]:
    """Resolve which profiles should be validated."""
    if args.all and args.name is not None:
        raise ProfileStoreError("specify a profile name or --all, not both")

    if args.all:
        target_names = store.available_profile_names()
    elif args.name is not None:
        target_names = (args.name,)
    else:
        active_profile_name = store.get_active_profile_name()
        target_names = (active_profile_name,) if active_profile_name is not None else store.available_profile_names()

    if not target_names:
        raise ProfileStoreError("no profiles configured")

    return target_names


def _render_validation_results(results: tuple[ProfileValidationResult, ...]) -> None:
    """Render validation results in text format."""
    for index, result in enumerate(results):
        if index:
            print()
        print(f"profile: {result.name}")
        print(f"status: {'ok' if result.ok else 'invalid'}")
        for message in result.definition_errors:
            print(f"definition_error: {message}")
        for message in result.readiness_errors:
            print(f"readiness_error: {message}")


def _exit_with_error(message: str) -> int:
    """Print an error message and return a failing exit code."""
    print(message, file=sys.stderr)
    return 1
