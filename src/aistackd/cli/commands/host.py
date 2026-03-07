"""Host command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.control_plane import ControlPlaneError, serve_control_plane
from aistackd.runtime.host import (
    DEFAULT_HOST_API_KEY_ENV,
    DEFAULT_HOST_BIND,
    DEFAULT_HOST_PORT,
    HostServiceConfig,
    validate_host_runtime,
)
from aistackd.state.host import HostStateError, HostStateStore


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``host`` command."""
    parser = subparsers.add_parser("host", help="inspect and run host runtime state")
    _add_shared_arguments(parser)
    _add_format_argument(parser)
    parser.set_defaults(handler=handle_status)

    command_parsers = parser.add_subparsers(dest="host_command", metavar="host_command")

    status_parser = command_parsers.add_parser("status", help="show the current host runtime state")
    _add_shared_arguments(status_parser)
    _add_format_argument(status_parser)
    status_parser.set_defaults(handler=handle_status)

    validate_parser = command_parsers.add_parser("validate", help="validate host runtime readiness")
    _add_shared_arguments(validate_parser)
    _add_service_arguments(validate_parser)
    _add_format_argument(validate_parser)
    validate_parser.set_defaults(handler=handle_validate)

    serve_parser = command_parsers.add_parser("serve", help="run the local authenticated control-plane service")
    _add_shared_arguments(serve_parser)
    _add_service_arguments(serve_parser)
    serve_parser.set_defaults(handler=handle_serve)


def handle_status(args: argparse.Namespace) -> int:
    """Render the current host runtime state."""
    try:
        runtime_state = HostStateStore(args.project_root).load_runtime_state()
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(runtime_state.to_dict(), indent=2))
        return 0

    print("host runtime state")
    print(f"backend: {runtime_state.backend}")
    print(f"backend_policy: {runtime_state.backend_policy}")
    print(f"model_source_policy: {runtime_state.model_source_policy}")
    print(f"active_model: {runtime_state.active_model or 'none'}")
    print(f"active_source: {runtime_state.active_source or 'none'}")
    print(f"activation_state: {runtime_state.activation_state}")
    print(f"installed_models: {len(runtime_state.installed_models)}")
    if runtime_state.installed_models:
        for record in runtime_state.installed_models:
            active_marker = "*" if record.model == runtime_state.active_model else " "
            print(
                f"{active_marker} {record.model}: source={record.source} "
                f"status={record.status} installed_at={record.installed_at}"
            )
    return 0


def handle_validate(args: argparse.Namespace) -> int:
    """Validate whether the host runtime is ready to serve locally."""
    try:
        result = validate_host_runtime(HostStateStore(args.project_root), _service_config_from_args(args))
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 1

    print("host validation")
    print(f"status: {'ok' if result.ok else 'invalid'}")
    print(f"base_url: {result.service.base_url}")
    print(f"responses_base_url: {result.service.responses_base_url}")
    print(f"api_key_env: {result.service.api_key_env}")
    print(f"active_model: {result.runtime.active_model or 'none'}")
    print(f"installed_models: {len(result.runtime.installed_models)}")
    for message in result.errors:
        print(f"error: {message}")
    return 0 if result.ok else 1


def handle_serve(args: argparse.Namespace) -> int:
    """Run the local authenticated control-plane service."""
    try:
        service = _service_config_from_args(args)
        result = validate_host_runtime(HostStateStore(args.project_root), service)
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if not result.ok:
        for message in result.errors:
            print(message, file=sys.stderr)
        return 1

    print("control plane serving")
    print(f"base_url: {result.service.base_url}")
    print(f"responses_base_url: {result.service.responses_base_url}")
    print(f"api_key_env: {result.service.api_key_env}")
    print(f"active_model: {result.runtime.active_model}")
    print("stop: Ctrl+C")
    try:
        serve_control_plane(args.project_root, result.service)
    except KeyboardInterrupt:
        print("control plane stopped")
        return 0
    except ControlPlaneError as exc:
        return _exit_with_error(str(exc))
    return 0


def _add_shared_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root containing the .aistackd state directory",
    )


def _add_service_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bind-host",
        default=DEFAULT_HOST_BIND,
        help=f"bind host for the local control plane (default: {DEFAULT_HOST_BIND})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HOST_PORT,
        help=f"bind port for the local control plane (default: {DEFAULT_HOST_PORT})",
    )
    parser.add_argument(
        "--api-key-env",
        default=DEFAULT_HOST_API_KEY_ENV,
        help=f"environment variable containing the control-plane API key (default: {DEFAULT_HOST_API_KEY_ENV})",
    )


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )


def _service_config_from_args(args: argparse.Namespace) -> HostServiceConfig:
    return HostServiceConfig(
        bind_host=args.bind_host,
        port=args.port,
        api_key_env=args.api_key_env,
    ).normalized()


def _exit_with_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1

