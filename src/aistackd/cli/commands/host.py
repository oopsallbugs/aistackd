"""Host command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.control_plane import ControlPlaneError, serve_control_plane
from aistackd.runtime.backend_process import (
    BackendProcessError,
    launch_managed_backend_process,
    restart_managed_backend_process,
    stop_current_managed_backend_process,
    stop_managed_backend_process,
)
from aistackd.runtime.backends import BackendAcquisitionError, acquire_managed_llama_cpp_installation, adopt_backend_installation
from aistackd.runtime.hardware import LLMFIT_BINARY_NAME
from aistackd.runtime.host import (
    DEFAULT_BACKEND_BIND,
    DEFAULT_BACKEND_PORT,
    DEFAULT_HOST_API_KEY_ENV,
    DEFAULT_HOST_BIND,
    DEFAULT_HOST_PORT,
    HostServiceConfig,
    validate_backend_runtime,
    validate_host_runtime,
)
from aistackd.runtime.prereqs import inspect_host_environment
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

    inspect_parser = command_parsers.add_parser(
        "inspect",
        help="inspect prerequisites, llmfit hardware detection, and backend discovery",
    )
    _add_shared_arguments(inspect_parser)
    _add_backend_locator_arguments(inspect_parser)
    _add_llmfit_arguments(inspect_parser)
    _add_format_argument(inspect_parser)
    inspect_parser.set_defaults(handler=handle_inspect)

    acquire_parser = command_parsers.add_parser(
        "acquire-backend",
        help="adopt an existing llama.cpp installation or acquire one with prebuilt-first source fallback",
    )
    _add_shared_arguments(acquire_parser)
    _add_backend_locator_arguments(acquire_parser)
    _add_llmfit_arguments(acquire_parser)
    _add_backend_acquisition_arguments(acquire_parser)
    _add_format_argument(acquire_parser)
    acquire_parser.set_defaults(handler=handle_acquire_backend)

    validate_parser = command_parsers.add_parser("validate", help="validate host runtime readiness")
    _add_shared_arguments(validate_parser)
    _add_service_arguments(validate_parser)
    _add_format_argument(validate_parser)
    validate_parser.set_defaults(handler=handle_validate)

    stop_parser = command_parsers.add_parser("stop", help="stop the managed backend process if it is running")
    _add_shared_arguments(stop_parser)
    _add_format_argument(stop_parser)
    stop_parser.set_defaults(handler=handle_stop)

    restart_parser = command_parsers.add_parser("restart", help="restart the managed backend process")
    _add_shared_arguments(restart_parser)
    _add_service_arguments(restart_parser)
    _add_format_argument(restart_parser)
    restart_parser.set_defaults(handler=handle_restart)

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
    print(f"backend_status: {runtime_state.backend_status}")
    print(f"backend_process_status: {runtime_state.backend_process_status}")
    if runtime_state.backend_installation is not None:
        print(f"backend_root: {runtime_state.backend_installation.backend_root}")
        print(f"server_binary: {runtime_state.backend_installation.server_binary}")
        print(f"acquisition_method: {runtime_state.backend_installation.acquisition_method}")
        if runtime_state.backend_installation.cli_binary is not None:
            print(f"cli_binary: {runtime_state.backend_installation.cli_binary}")
    if runtime_state.backend_process is not None:
        print(f"backend_pid: {runtime_state.backend_process.pid}")
        print(f"backend_base_url: {runtime_state.backend_process.base_url}")
        print(f"backend_log_path: {runtime_state.backend_process.log_path}")
    print(f"active_model: {runtime_state.active_model or 'none'}")
    print(f"active_source: {runtime_state.active_source or 'none'}")
    print(f"activation_state: {runtime_state.activation_state}")
    print(f"installed_models: {len(runtime_state.installed_models)}")
    if runtime_state.installed_models:
        for record in runtime_state.installed_models:
            active_marker = "*" if record.model == runtime_state.active_model else " "
            print(
                f"{active_marker} {record.model}: source={record.source} "
                f"method={record.acquisition_method} status={record.status} installed_at={record.installed_at}"
            )
    return 0


def handle_inspect(args: argparse.Namespace) -> int:
    """Inspect host prerequisites, llmfit hardware detection, and backend discovery state."""
    report = inspect_host_environment(
        backend_root=args.backend_root,
        server_binary=args.server_binary,
        cli_binary=args.cli_binary,
        llmfit_binary=args.llmfit_binary,
    )
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print("host inspection")
    print(f"status: {'ok' if report.ok else 'needs_attention'}")
    print(f"prerequisites_status: {'ok' if report.prerequisites_ok else 'needs_attention'}")
    for check in report.prerequisite_checks:
        label = "ok" if check.ok else "missing"
        print(f"prerequisite: {check.name} status={label} detail={check.detail}")
    print(f"hardware_detection: {'ok' if report.hardware_detection_ok else 'needs_attention'}")
    print(f"llmfit_command: {' '.join(report.hardware_detection.command)}")
    if report.hardware_detection.profile is not None:
        profile = report.hardware_detection.profile
        print(f"hardware_backend: {profile.backend}")
        print(f"hardware_acceleration_api: {profile.acceleration_api}")
        print(f"hardware_target: {profile.target or 'none'}")
        print(f"source_cmake_flags: {', '.join(profile.cmake_flags) if profile.cmake_flags else 'none'}")
        for warning in profile.warnings:
            print(f"warning: {warning}")
    for issue in report.hardware_detection.issues:
        print(f"issue: {issue}")
    discovery = report.backend_discovery
    print(f"backend_discovery: {'found' if discovery.found else 'missing'}")
    print(f"discovery_mode: {discovery.discovery_mode}")
    if discovery.backend_root is not None:
        print(f"backend_root: {discovery.backend_root}")
    if discovery.server_binary is not None:
        print(f"server_binary: {discovery.server_binary}")
    if discovery.cli_binary is not None:
        print(f"cli_binary: {discovery.cli_binary}")
    for issue in discovery.issues:
        print(f"issue: {issue}")
    if report.acquisition_plan is not None:
        print(f"acquisition_flavor: {report.acquisition_plan.flavor}")
        print(f"acquisition_primary: {report.acquisition_plan.primary_strategy}")
        print(f"acquisition_fallback: {report.acquisition_plan.fallback_strategy}")
        for key, value in report.acquisition_plan.source_environment:
            print(f"source_env: {key}={value}")
        for note in report.acquisition_plan.notes:
            print(f"note: {note}")
    return 0


def handle_acquire_backend(args: argparse.Namespace) -> int:
    """Adopt an existing llama.cpp installation or plan backend acquisition."""
    has_existing_locator = any(
        value is not None
        for value in (args.backend_root, args.server_binary, args.cli_binary)
    )
    has_acquisition_input = any(
        value is not None
        for value in (args.prebuilt_root, args.prebuilt_archive, args.source_root)
    )
    if has_existing_locator and has_acquisition_input:
        return _exit_with_error(
            "existing-backend locator flags cannot be combined with managed acquisition inputs"
        )

    report = inspect_host_environment(
        backend_root=args.backend_root,
        server_binary=args.server_binary,
        cli_binary=args.cli_binary,
        llmfit_binary=args.llmfit_binary,
    )
    discovery = report.backend_discovery
    try:
        if has_acquisition_input:
            if report.acquisition_plan is None:
                detail = (
                    "; ".join(report.hardware_detection.issues)
                    or "hardware detection did not produce a backend acquisition plan"
                )
                return _exit_with_error(detail)
            acquisition = acquire_managed_llama_cpp_installation(
                args.project_root,
                report.acquisition_plan,
                prebuilt_root=args.prebuilt_root,
                prebuilt_archive=args.prebuilt_archive,
                source_root=args.source_root,
                jobs=args.jobs,
            )
            installation = acquisition.installation
            created = HostStateStore(args.project_root).save_backend_installation(installation)
            action = "acquired" if created else "updated"
        elif discovery.found:
            installation = adopt_backend_installation(discovery)
            created = HostStateStore(args.project_root).save_backend_installation(installation)
            acquisition = None
            action = "adopted" if created else "updated"
        elif report.acquisition_plan is None:
            issues = [*report.hardware_detection.issues, *discovery.issues]
            detail = "; ".join(issue for issue in issues if issue) or "unable to plan backend acquisition"
            return _exit_with_error(detail)
        else:
            installation = None
            acquisition = None
            created = False
            action = "planned"
    except (BackendAcquisitionError, HostStateError, ValueError) as exc:
        return _exit_with_error(str(exc))

    if installation is not None:
        payload = {
            "action": action,
            "backend_installation": installation.as_dict(),
            "hardware_detection": report.hardware_detection.to_dict(),
            "acquisition_plan": (
                report.acquisition_plan.to_dict() if report.acquisition_plan is not None else None
            ),
            "acquisition": acquisition.to_dict() if acquisition is not None else None,
            "issues": list(discovery.issues),
        }
    else:
        payload = {
            "action": action,
            "hardware_detection": report.hardware_detection.to_dict(),
            "acquisition_plan": report.acquisition_plan.to_dict() if report.acquisition_plan is not None else None,
            "issues": list(report.hardware_detection.issues),
        }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    if installation is not None:
        print(f"{payload['action']} backend installation")
        if acquisition is not None:
            print(f"strategy: {acquisition.strategy}")
            for attempt in acquisition.attempts:
                status = "ok" if attempt.ok else "failed"
                print(f"attempt: {attempt.strategy} status={status} detail={attempt.detail}")
        print(f"backend_root: {installation.backend_root}")
        print(f"server_binary: {installation.server_binary}")
        if installation.cli_binary is not None:
            print(f"cli_binary: {installation.cli_binary}")
        for issue in discovery.issues:
            print(f"issue: {issue}")
        return 0

    print("planned backend acquisition")
    print(f"llmfit_command: {' '.join(report.hardware_detection.command)}")
    if report.hardware_detection.profile is not None:
        print(f"hardware_backend: {report.hardware_detection.profile.backend}")
        print(f"hardware_acceleration_api: {report.hardware_detection.profile.acceleration_api}")
    print(f"acquisition_flavor: {report.acquisition_plan.flavor}")
    print(f"acquisition_primary: {report.acquisition_plan.primary_strategy}")
    print(f"acquisition_fallback: {report.acquisition_plan.fallback_strategy}")
    if report.acquisition_plan.source_cmake_flags:
        print(f"source_cmake_flags: {', '.join(report.acquisition_plan.source_cmake_flags)}")
    for key, value in report.acquisition_plan.source_environment:
        print(f"source_env: {key}={value}")
    for warning in report.acquisition_plan.warnings:
        print(f"warning: {warning}")
    for note in report.acquisition_plan.notes:
        print(f"note: {note}")
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
    print(f"backend_base_url: {result.service.backend_base_url}")
    print(f"api_key_env: {result.service.api_key_env}")
    print(f"backend_status: {result.runtime.backend_status}")
    print(f"backend_process_status: {result.runtime.backend_process_status}")
    if result.runtime.backend_installation is not None:
        print(f"server_binary: {result.runtime.backend_installation.server_binary}")
    print(f"active_model: {result.runtime.active_model or 'none'}")
    print(f"installed_models: {len(result.runtime.installed_models)}")
    for message in result.errors:
        print(f"error: {message}")
    return 0 if result.ok else 1


def handle_serve(args: argparse.Namespace) -> int:
    """Run the local authenticated control-plane service."""
    try:
        service = _service_config_from_args(args)
        store = HostStateStore(args.project_root)
        result = validate_host_runtime(store, service)
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if not result.ok:
        for message in result.errors:
            print(message, file=sys.stderr)
        return 1

    try:
        running_process = launch_managed_backend_process(store, result.service)
    except (BackendProcessError, HostStateError) as exc:
        return _exit_with_error(str(exc))

    print("control plane serving")
    print(f"base_url: {result.service.base_url}")
    print(f"responses_base_url: {result.service.responses_base_url}")
    print(f"backend_base_url: {result.service.backend_base_url}")
    print(f"api_key_env: {result.service.api_key_env}")
    if result.runtime.backend_installation is not None:
        print(f"server_binary: {result.runtime.backend_installation.server_binary}")
    print(f"backend_pid: {running_process.record.pid}")
    print(f"backend_log_path: {running_process.record.log_path}")
    print(f"active_model: {result.runtime.active_model}")
    print("stop: Ctrl+C")
    try:
        serve_control_plane(args.project_root, result.service)
    except KeyboardInterrupt:
        print("control plane stopped")
        return 0
    except ControlPlaneError as exc:
        return _exit_with_error(str(exc))
    finally:
        stop_managed_backend_process(store, running_process)
    return 0


def handle_stop(args: argparse.Namespace) -> int:
    """Stop the currently persisted managed backend process."""
    try:
        store = HostStateStore(args.project_root)
        runtime_before = store.load_runtime_state()
        record = stop_current_managed_backend_process(store)
        runtime_after = store.load_runtime_state()
    except (BackendProcessError, HostStateError) as exc:
        return _exit_with_error(str(exc))

    stopped = runtime_before.backend_process_status in {"running", "starting"} and runtime_after.backend_process_status == "stopped"
    payload = {
        "action": "stopped" if stopped else "already_stopped",
        "before_status": runtime_before.backend_process_status,
        "after_status": runtime_after.backend_process_status,
        "backend_process": record.as_dict() if record is not None else None,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    if stopped:
        print("managed backend stopped")
    else:
        print("managed backend was not running")
    print(f"before_status: {payload['before_status']}")
    print(f"after_status: {payload['after_status']}")
    if record is not None:
        print(f"backend_pid: {record.pid}")
        print(f"backend_log_path: {record.log_path}")
    return 0


def handle_restart(args: argparse.Namespace) -> int:
    """Restart the managed backend process."""
    try:
        store = HostStateStore(args.project_root)
        service = _service_config_from_args(args)
        result = validate_backend_runtime(store, service)
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if not result.ok:
        for message in result.errors:
            print(message, file=sys.stderr)
        return 1

    before_status = result.runtime.backend_process_status
    try:
        running_process = restart_managed_backend_process(store, result.service)
    except (BackendProcessError, HostStateError) as exc:
        return _exit_with_error(str(exc))

    payload = {
        "action": "restarted" if before_status in {"running", "starting"} else "started",
        "before_status": before_status,
        "after_status": "running",
        "backend_process": running_process.record.as_dict(),
        "service": result.service.to_dict(),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"managed backend {payload['action']}")
    print(f"before_status: {payload['before_status']}")
    print(f"after_status: {payload['after_status']}")
    print(f"backend_pid: {running_process.record.pid}")
    print(f"backend_base_url: {running_process.record.base_url}")
    print(f"backend_log_path: {running_process.record.log_path}")
    print(f"active_model: {running_process.record.model}")
    return 0


def _add_shared_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root containing the .aistackd state directory",
    )


def _add_backend_locator_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend-root",
        type=Path,
        help="existing llama.cpp root containing a bin/ directory",
    )
    parser.add_argument(
        "--server-binary",
        type=Path,
        help="explicit path to an existing llama-server binary",
    )
    parser.add_argument(
        "--cli-binary",
        type=Path,
        help="explicit path to an existing llama-cli binary",
    )


def _add_llmfit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--llmfit-binary",
        default=LLMFIT_BINARY_NAME,
        help=f"llmfit executable to use for hardware detection (default: {LLMFIT_BINARY_NAME})",
    )


def _add_backend_acquisition_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prebuilt-root",
        type=Path,
        help="path to a local prebuilt llama.cpp root to copy into managed host state",
    )
    parser.add_argument(
        "--prebuilt-archive",
        type=Path,
        help="path to a local prebuilt llama.cpp archive to unpack into managed host state",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="path to a local llama.cpp source tree used when prebuilt acquisition is unavailable",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        help="override the parallel build job count for source fallback",
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
    parser.add_argument(
        "--backend-bind-host",
        default=DEFAULT_BACKEND_BIND,
        help=f"bind host for the managed llama.cpp process (default: {DEFAULT_BACKEND_BIND})",
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=DEFAULT_BACKEND_PORT,
        help=f"bind port for the managed llama.cpp process (default: {DEFAULT_BACKEND_PORT})",
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
        backend_bind_host=args.backend_bind_host,
        backend_port=args.backend_port,
    ).normalized()


def _exit_with_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1
