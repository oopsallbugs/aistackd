"""Client command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.frontends.catalog import SUPPORTED_FRONTENDS
from aistackd.runtime.config import RuntimeConfig
from aistackd.runtime.remote import (
    RemoteClientError,
    activate_remote_model,
    fetch_remote_models,
    fetch_remote_runtime,
    install_remote_model,
    recommend_remote_models,
    search_remote_models,
    validate_remote_runtime,
)
from aistackd.state.profiles import ProfileStore, ProfileStoreError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``client`` command."""
    parser = subparsers.add_parser("client", help="inspect and operate against the active remote profile")
    _add_common_arguments(parser)
    parser.set_defaults(handler=handle_show)

    command_parsers = parser.add_subparsers(dest="client_command", metavar="client_command")

    show_parser = command_parsers.add_parser("show", help="show the active client runtime config")
    _add_common_arguments(show_parser)
    show_parser.set_defaults(handler=handle_show)

    validate_parser = command_parsers.add_parser("validate", help="validate remote connectivity and auth")
    _add_common_arguments(validate_parser)
    validate_parser.set_defaults(handler=handle_validate)

    runtime_parser = command_parsers.add_parser("runtime", help="fetch remote runtime state")
    _add_common_arguments(runtime_parser)
    runtime_parser.set_defaults(handler=handle_runtime)

    models_parser = command_parsers.add_parser("models", help="manage remote models through the active profile")
    _add_common_arguments(models_parser)
    models_parser.set_defaults(handler=handle_models_installed)

    model_commands = models_parser.add_subparsers(dest="client_models_command", metavar="client_models_command")

    installed_parser = model_commands.add_parser("installed", help="list installed remote models")
    _add_common_arguments(installed_parser)
    installed_parser.set_defaults(handler=handle_models_installed)

    search_parser = model_commands.add_parser("search", help="search the remote llmfit catalog")
    _add_common_arguments(search_parser)
    search_parser.add_argument("query", nargs="?", help="optional query string")
    search_parser.set_defaults(handler=handle_models_search)

    recommend_parser = model_commands.add_parser("recommend", help="show remote llmfit recommendations")
    _add_common_arguments(recommend_parser)
    recommend_parser.set_defaults(handler=handle_models_recommend)

    install_parser = model_commands.add_parser("install", help="install one model through the remote host")
    _add_common_arguments(install_parser)
    install_parser.add_argument("model", nargs="?", help="model identifier to install")
    install_parser.add_argument("--source", choices=("llmfit", "hugging_face"), help="force one model source")
    install_parser.add_argument("--gguf-path", help="explicit path to a local GGUF visible to the remote host")
    install_parser.add_argument(
        "--local-root",
        dest="local_roots",
        action="append",
        default=[],
        help="additional local root on the remote host to scan for matching GGUF files",
    )
    install_parser.add_argument("--hf-url", help="Hugging Face model/file URL to use for fallback acquisition")
    install_parser.add_argument("--hf-repo", help="Hugging Face repo to use for fallback acquisition")
    install_parser.add_argument("--hf-file", help="GGUF filename to use for Hugging Face fallback")
    install_parser.add_argument("--hf-cli", help="Hugging Face CLI executable to use for fallback downloads")
    install_parser.add_argument("--quant", help="preferred llmfit quantization for direct downloads")
    install_parser.add_argument("--budget", dest="budget_gb", type=float, help="llmfit memory budget in GB")
    install_parser.add_argument("--activate", action="store_true", help="activate the model after installing it")
    install_parser.set_defaults(handler=handle_models_install)

    activate_parser = model_commands.add_parser("activate", help="activate one installed remote model")
    _add_common_arguments(activate_parser)
    activate_parser.add_argument("model", help="installed model identifier to activate")
    activate_parser.set_defaults(handler=handle_models_activate)


def handle_show(args: argparse.Namespace) -> int:
    """Render the active client runtime config."""
    try:
        runtime_config = _load_runtime_config(args.project_root)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(runtime_config.to_dict(), indent=2))
        return 0

    _print_runtime_config(runtime_config)
    return 0


def handle_validate(args: argparse.Namespace) -> int:
    """Validate connectivity and auth for the active remote profile."""
    try:
        runtime_config = _load_runtime_config(args.project_root)
        validation = validate_remote_runtime(runtime_config)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(validation.to_dict(), indent=2))
        return 0 if validation.ok else 1

    print("client validation")
    print(f"active_profile: {validation.active_profile}")
    print(f"base_url: {validation.base_url}")
    print(f"responses_base_url: {validation.responses_base_url}")
    print(f"status: {'ok' if validation.ok else 'invalid'}")
    if validation.health is not None:
        print(f"health_status_code: {validation.health.status_code}")
        print(f"remote_health: {validation.health.payload.get('status')}")
    if validation.models is not None:
        print(f"models_status_code: {validation.models.status_code}")
    if validation.runtime is not None:
        print(f"runtime_status_code: {validation.runtime.status_code}")
    for message in validation.errors:
        print(f"error: {message}")
    return 0 if validation.ok else 1


def handle_runtime(args: argparse.Namespace) -> int:
    """Fetch remote runtime state."""
    try:
        runtime_config = _load_runtime_config(args.project_root)
        payload = fetch_remote_runtime(runtime_config)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    runtime = payload.get("runtime")
    service = payload.get("service")
    print("remote runtime")
    if isinstance(runtime, dict):
        print(f"active_model: {runtime.get('active_model') or 'none'}")
        print(f"backend_status: {runtime.get('backend_status')}")
        print(f"backend_process_status: {runtime.get('backend_process_status')}")
        installed_models = runtime.get("installed_models")
        if isinstance(installed_models, list):
            print(f"installed_models: {len(installed_models)}")
    if isinstance(service, dict):
        print(f"service_base_url: {service.get('base_url')}")
        print(f"responses_base_url: {service.get('responses_base_url')}")
    return 0


def handle_models_installed(args: argparse.Namespace) -> int:
    """List installed remote models."""
    try:
        runtime_config = _load_runtime_config(args.project_root)
        payload = fetch_remote_models(runtime_config)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"active_model: {payload.get('active_model') or 'none'}")
    models = payload.get("data")
    print(f"installed_models: {len(models) if isinstance(models, list) else 0}")
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            active_marker = "*" if entry.get("active") else " "
            print(
                f"{active_marker} {entry.get('id')}: "
                f"source={entry.get('source')} method={entry.get('acquisition_method')} status={entry.get('status')}"
            )
    return 0


def handle_models_search(args: argparse.Namespace) -> int:
    """Search remote models through the control plane."""
    try:
        runtime_config = _load_runtime_config(args.project_root)
        payload = search_remote_models(runtime_config, args.query)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    _print_remote_model_list("available_models", payload)
    return 0


def handle_models_recommend(args: argparse.Namespace) -> int:
    """Recommend remote models through the control plane."""
    try:
        runtime_config = _load_runtime_config(args.project_root)
        payload = recommend_remote_models(runtime_config)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    _print_remote_model_list("recommended_models", payload)
    return 0


def handle_models_install(args: argparse.Namespace) -> int:
    """Install a remote model through the authenticated admin API."""
    try:
        if args.budget_gb is not None and args.budget_gb <= 0:
            return _exit_with_error("--budget must be positive when provided")
        runtime_config = _load_runtime_config(args.project_root)
        payload: dict[str, object] = {"activate": args.activate}
        if args.model is not None:
            payload["model"] = args.model
        for field_name in ("source", "gguf_path", "hf_url", "hf_repo", "hf_file", "hf_cli", "quant"):
            value = getattr(args, field_name)
            if value is not None:
                payload[field_name] = value
        if args.budget_gb is not None:
            payload["budget_gb"] = args.budget_gb
        if args.local_roots:
            payload["local_roots"] = list(args.local_roots)
        response_payload = install_remote_model(runtime_config, payload)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(response_payload, indent=2))
        return 0

    model = response_payload.get("model")
    if isinstance(model, dict):
        print(f"{response_payload.get('action')}: {model.get('model')}")
        print(f"source: {model.get('source')}")
        print(f"acquisition_method: {model.get('acquisition_method')}")
        print(f"artifact_path: {model.get('artifact_path')}")
    print(f"active_model: {response_payload.get('active_model') or 'none'}")
    return 0


def handle_models_activate(args: argparse.Namespace) -> int:
    """Activate one installed remote model."""
    try:
        runtime_config = _load_runtime_config(args.project_root)
        payload = activate_remote_model(runtime_config, args.model)
    except (ProfileStoreError, RemoteClientError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    runtime = payload.get("runtime")
    print(f"activated model '{args.model}'")
    if isinstance(runtime, dict):
        print(f"active_model: {runtime.get('active_model') or 'none'}")
        print(f"activation_state: {runtime.get('activation_state')}")
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
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


def _load_runtime_config(project_root: Path) -> RuntimeConfig:
    profile_store = ProfileStore(project_root)
    profile = profile_store.get_active_profile()
    if profile is None:
        raise ProfileStoreError("no active profile is set")
    return RuntimeConfig.for_client(profile, SUPPORTED_FRONTENDS)


def _print_runtime_config(runtime_config: RuntimeConfig) -> None:
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


def _print_remote_model_list(label: str, payload: dict[str, object]) -> None:
    models = payload.get("models")
    print(f"{label}: {len(models) if isinstance(models, list) else 0}")
    if not isinstance(models, list):
        return
    for entry in models:
        if not isinstance(entry, dict):
            continue
        parts = [
            str(entry.get("name")),
            f"source={entry.get('source')}",
            f"context={entry.get('context_window')}",
            f"quantization={entry.get('quantization')}",
        ]
        rank = entry.get("recommended_rank")
        if rank is not None:
            parts.append(f"recommended_rank={rank}")
        parts.append(f"summary={entry.get('summary')}")
        print(" ".join(parts))


def _exit_with_error(message: str) -> int:
    """Print a client command error and return a failing exit code."""
    print(message, file=sys.stderr)
    return 1
