"""Models command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.models.sources import (
    SUPPORTED_MODEL_SOURCES,
    SourceModel,
    recommend_models,
    resolve_source_model,
    search_models,
)
from aistackd.state.host import HostStateError, HostStateStore, InstalledModelNotFoundError
from aistackd.state.profiles import Profile, ProfileStore, ProfileStoreError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``models`` command."""
    parser = subparsers.add_parser("models", help="inspect profile targets and host model state")
    _add_common_arguments(parser)
    parser.set_defaults(handler=handle_show)

    command_parsers = parser.add_subparsers(dest="models_command", metavar="models_command")

    list_parser = command_parsers.add_parser("list", help="list configured profile models")
    _add_common_arguments(list_parser)
    list_parser.set_defaults(handler=handle_list)

    show_parser = command_parsers.add_parser("show", help="show the target model for one profile")
    _add_common_arguments(show_parser)
    show_parser.add_argument("name", nargs="?", help="profile name to inspect; defaults to the active profile")
    show_parser.set_defaults(handler=handle_show)

    set_parser = command_parsers.add_parser("set", help="set the target model for a profile")
    _add_common_arguments(set_parser)
    set_parser.add_argument("model", help="model identifier to store on the profile")
    set_parser.add_argument(
        "--profile",
        dest="profile_name",
        help="profile name to update; defaults to the active profile",
    )
    set_parser.set_defaults(handler=handle_set)

    search_parser = command_parsers.add_parser("search", help="search available host-side model sources")
    _add_common_arguments(search_parser)
    search_parser.add_argument("query", nargs="?", help="optional query string")
    search_parser.add_argument("--source", choices=SUPPORTED_MODEL_SOURCES, help="restrict to one model source")
    search_parser.add_argument(
        "--recommended-only",
        action="store_true",
        help="only show models that are part of the recommended set",
    )
    search_parser.set_defaults(handler=handle_search)

    recommend_parser = command_parsers.add_parser("recommend", help="show policy-ranked recommended models")
    _add_common_arguments(recommend_parser)
    recommend_parser.add_argument("--source", choices=SUPPORTED_MODEL_SOURCES, help="restrict to one model source")
    recommend_parser.set_defaults(handler=handle_recommend)

    installed_parser = command_parsers.add_parser("installed", help="list installed host models")
    _add_common_arguments(installed_parser)
    installed_parser.set_defaults(handler=handle_installed)

    install_parser = command_parsers.add_parser("install", help="install a model into host state")
    _add_common_arguments(install_parser)
    install_parser.add_argument("model", help="model identifier to install")
    install_parser.add_argument("--source", choices=SUPPORTED_MODEL_SOURCES, help="force one model source")
    install_parser.add_argument("--activate", action="store_true", help="activate the model after installing it")
    install_parser.set_defaults(handler=handle_install)

    activate_parser = command_parsers.add_parser("activate", help="activate an installed host model")
    _add_common_arguments(activate_parser)
    activate_parser.add_argument("model", help="installed model identifier to activate")
    activate_parser.set_defaults(handler=handle_activate)


def handle_list(args: argparse.Namespace) -> int:
    """List target models for all configured profiles."""
    try:
        store = ProfileStore(args.project_root)
        profiles = store.list_profiles()
        active_profile_name = store.get_active_profile_name()
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        payload = {
            "profiles": [_profile_model_payload(profile, active_profile_name) for profile in profiles],
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
    """Show the target model for one profile."""
    try:
        store = ProfileStore(args.project_root)
        active_profile_name = store.get_active_profile_name()
        profile_name = getattr(args, "name", None)
        profile = store.load_profile(profile_name) if profile_name else store.get_active_profile()
        if profile is None:
            return _exit_with_error("no active profile is set")
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    payload = _profile_model_payload(profile, active_profile_name)
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"profile: {profile.name}")
    print(f"model: {profile.model}")
    print(f"active: {'yes' if payload['active'] else 'no'}")
    print(f"base_url: {profile.base_url}")
    return 0


def handle_set(args: argparse.Namespace) -> int:
    """Update the target model for one profile."""
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

    payload = _profile_model_payload(updated_profile, active_profile_name)
    if args.format == "json":
        print(json.dumps({"action": "updated", "profile": payload}, indent=2))
        return 0

    print(f"updated model for profile '{updated_profile.name}'")
    print(f"model: {updated_profile.model}")
    return 0


def handle_search(args: argparse.Namespace) -> int:
    """Search the available model-source catalogs."""
    try:
        models = search_models(args.query, source=args.source, recommended_only=args.recommended_only)
    except ValueError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(
            json.dumps(
                {
                    "query": args.query,
                    "source": args.source,
                    "recommended_only": args.recommended_only,
                    "models": [model.as_dict() for model in models],
                },
                indent=2,
            )
        )
        return 0

    print(f"available_models: {len(models)}")
    for model in models:
        print(_format_source_model_line(model))
    return 0


def handle_recommend(args: argparse.Namespace) -> int:
    """Show policy-ranked recommended models."""
    try:
        models = recommend_models(source=args.source)
    except ValueError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(
            json.dumps(
                {
                    "source": args.source,
                    "models": [model.as_dict() for model in models],
                },
                indent=2,
            )
        )
        return 0

    print(f"recommended_models: {len(models)}")
    for model in models:
        print(_format_source_model_line(model))
    return 0


def handle_installed(args: argparse.Namespace) -> int:
    """List installed host models."""
    try:
        store = HostStateStore(args.project_root)
        runtime_state = store.load_runtime_state()
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        payload = {
            "active_model": runtime_state.active_model,
            "models": [record.as_dict() for record in runtime_state.installed_models],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"installed_models: {len(runtime_state.installed_models)}")
    for record in runtime_state.installed_models:
        active_marker = "*" if record.model == runtime_state.active_model else " "
        print(
            f"{active_marker} {record.model}: source={record.source} "
            f"status={record.status} installed_at={record.installed_at}"
        )
    return 0


def handle_install(args: argparse.Namespace) -> int:
    """Install one model into host state."""
    try:
        source_model = resolve_source_model(args.model, source=args.source)
        if source_model is None:
            return _exit_with_error(f"model '{args.model}' was not found in the configured sources")
        store = HostStateStore(args.project_root)
        record, created = store.install_model(source_model)
        runtime_state = store.activate_model(record.model) if args.activate else store.load_runtime_state()
    except (HostStateError, InstalledModelNotFoundError, ValueError) as exc:
        return _exit_with_error(str(exc))

    action = "installed" if created else "updated"
    payload = {
        "action": action,
        "model": record.as_dict(),
        "active_model": runtime_state.active_model,
        "activation_state": runtime_state.activation_state,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"{action} model '{record.model}' from {record.source}")
    if args.activate:
        print(f"active_model: {runtime_state.active_model}")
    return 0


def handle_activate(args: argparse.Namespace) -> int:
    """Activate one installed host model."""
    try:
        runtime_state = HostStateStore(args.project_root).activate_model(args.model)
    except (HostStateError, InstalledModelNotFoundError) as exc:
        return _exit_with_error(str(exc))

    payload = runtime_state.to_dict()
    if args.format == "json":
        print(json.dumps({"action": "activated", "runtime": payload}, indent=2))
        return 0

    print(f"activated model '{args.model}'")
    print(f"active_source: {runtime_state.active_source}")
    print(f"activation_state: {runtime_state.activation_state}")
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


def _profile_model_payload(profile: Profile, active_profile_name: str | None) -> dict[str, object]:
    """Build a stable JSON payload for one profile model."""
    return {
        "profile": profile.name,
        "model": profile.model,
        "active": profile.name == active_profile_name,
        "base_url": profile.base_url,
        "schema_version": profile.schema_version,
    }


def _format_source_model_line(model: SourceModel) -> str:
    parts = [
        f"{model.name}",
        f"source={model.source}",
        f"context={model.context_window}",
        f"quantization={model.quantization}",
    ]
    if model.recommended_rank is not None:
        parts.append(f"recommended_rank={model.recommended_rank}")
    parts.append(f"summary={model.summary}")
    return " ".join(parts)


def _exit_with_error(message: str) -> int:
    """Print an error message and return a failing exit code."""
    print(message, file=sys.stderr)
    return 1

