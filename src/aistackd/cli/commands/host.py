"""Host command implementation."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
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
from aistackd.runtime.bootstrap import (
    DEFAULT_USER_BIN_DIR,
    BootstrapError,
    install_tool,
    normalize_user_bin_dir,
    resolve_tool_binary,
)
from aistackd.runtime.control_plane_process import (
    ControlPlaneProcessError,
    build_control_plane_command,
    launch_control_plane_process,
    mark_current_control_plane_process_stopped,
    save_current_control_plane_process,
    stop_current_control_plane_process,
)
from aistackd.runtime.hardware import LLMFIT_BINARY_NAME
from aistackd.runtime.host import (
    DEFAULT_BACKEND_BIND,
    DEFAULT_BACKEND_CONTEXT_SIZE,
    DEFAULT_BACKEND_PREDICT_LIMIT,
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

    ps_parser = command_parsers.add_parser("ps", help="alias for 'host status'")
    _add_shared_arguments(ps_parser)
    _add_format_argument(ps_parser)
    ps_parser.set_defaults(handler=handle_status)

    inspect_parser = command_parsers.add_parser(
        "inspect",
        help="inspect prerequisites, llmfit hardware detection, and backend discovery",
    )
    _add_shared_arguments(inspect_parser)
    _add_backend_locator_arguments(inspect_parser)
    _add_llmfit_arguments(inspect_parser)
    _add_format_argument(inspect_parser)
    inspect_parser.set_defaults(handler=handle_inspect)

    install_llmfit_parser = command_parsers.add_parser("install-llmfit", help="install llmfit into a normal user bin directory")
    _add_shared_arguments(install_llmfit_parser)
    _add_user_bin_argument(install_llmfit_parser)
    _add_format_argument(install_llmfit_parser)
    install_llmfit_parser.set_defaults(handler=handle_install_llmfit)

    install_hf_parser = command_parsers.add_parser("install-hf", help="install the Hugging Face CLI into a normal user bin directory")
    _add_shared_arguments(install_hf_parser)
    _add_user_bin_argument(install_hf_parser)
    _add_format_argument(install_hf_parser)
    install_hf_parser.set_defaults(handler=handle_install_hf)

    bootstrap_parser = command_parsers.add_parser("bootstrap", help="prepare a clean host with operator tools and a managed backend")
    _add_shared_arguments(bootstrap_parser)
    _add_llmfit_arguments(bootstrap_parser)
    _add_user_bin_argument(bootstrap_parser)
    _add_service_arguments(bootstrap_parser)
    _add_backend_acquisition_arguments(bootstrap_parser)
    _add_format_argument(bootstrap_parser)
    bootstrap_parser.set_defaults(handler=handle_bootstrap)

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

    start_parser = command_parsers.add_parser("start", help="start the managed control-plane service in the background")
    _add_shared_arguments(start_parser)
    _add_service_arguments(start_parser)
    _add_format_argument(start_parser)
    start_parser.set_defaults(handler=handle_start)

    up_parser = command_parsers.add_parser("up", help="alias for 'host start'")
    _add_shared_arguments(up_parser)
    _add_service_arguments(up_parser)
    _add_format_argument(up_parser)
    up_parser.set_defaults(handler=handle_start)

    stop_parser = command_parsers.add_parser("stop", help="stop the managed backend process if it is running")
    _add_shared_arguments(stop_parser)
    _add_format_argument(stop_parser)
    stop_parser.add_argument(
        "--service",
        action="store_true",
        help="stop the managed control-plane service instead of only the backend process",
    )
    stop_parser.add_argument(
        "--all",
        action="store_true",
        help="stop both the managed control-plane service and any persisted backend process",
    )
    stop_parser.set_defaults(handler=handle_stop)

    down_parser = command_parsers.add_parser("down", help="alias for 'host stop --all'")
    _add_shared_arguments(down_parser)
    _add_format_argument(down_parser)
    down_parser.set_defaults(handler=handle_down, service=False, all=True)

    restart_parser = command_parsers.add_parser("restart", help="restart the managed backend process")
    _add_shared_arguments(restart_parser)
    _add_service_arguments(restart_parser)
    _add_format_argument(restart_parser)
    restart_parser.add_argument(
        "--service",
        action="store_true",
        help="restart the managed control-plane service instead of only the backend process",
    )
    restart_parser.set_defaults(handler=handle_restart)

    serve_parser = command_parsers.add_parser("serve", help="run the local authenticated control-plane service")
    _add_shared_arguments(serve_parser)
    _add_service_arguments(serve_parser)
    serve_parser.set_defaults(handler=handle_serve)

    logs_parser = command_parsers.add_parser("logs", help="show persisted backend or control-plane logs")
    _add_shared_arguments(logs_parser)
    logs_parser.add_argument("target", choices=("backend", "control-plane"), help="log target to print")
    logs_parser.add_argument(
        "--follow",
        action="store_true",
        help="follow the log output until interrupted",
    )
    logs_parser.add_argument(
        "--lines",
        type=int,
        default=40,
        help="number of lines to print before following (default: 40)",
    )
    logs_parser.set_defaults(handler=handle_logs)

    tune_parser = command_parsers.add_parser("tune", help="persist backend tuning defaults for host lifecycle commands")
    _add_shared_arguments(tune_parser)
    _add_format_argument(tune_parser)
    tune_commands = tune_parser.add_subparsers(dest="host_tune_command", metavar="host_tune_command")

    tune_show_parser = tune_commands.add_parser("show", help="show persisted backend tuning defaults")
    _add_shared_arguments(tune_show_parser)
    _add_format_argument(tune_show_parser)
    tune_show_parser.set_defaults(handler=handle_tune_show)

    tune_set_parser = tune_commands.add_parser("set", help="persist backend tuning defaults")
    _add_shared_arguments(tune_set_parser)
    _add_tuning_arguments(tune_set_parser)
    _add_format_argument(tune_set_parser)
    tune_set_parser.set_defaults(handler=handle_tune_set)

    tune_reset_parser = tune_commands.add_parser("reset", help="clear persisted backend tuning defaults")
    _add_shared_arguments(tune_reset_parser)
    _add_format_argument(tune_reset_parser)
    tune_reset_parser.set_defaults(handler=handle_tune_reset)


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
    print(f"control_plane_process_status: {runtime_state.control_plane_process_status}")
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
        if runtime_state.backend_process.context_size is not None:
            print(f"backend_context_size: {runtime_state.backend_process.context_size}")
        if runtime_state.backend_process.predict_limit is not None:
            print(f"backend_predict_limit: {runtime_state.backend_process.predict_limit}")
    if runtime_state.control_plane_process is not None:
        print(f"control_plane_pid: {runtime_state.control_plane_process.pid}")
        print(f"control_plane_base_url: {runtime_state.control_plane_process.base_url}")
        print(f"control_plane_log_path: {runtime_state.control_plane_process.log_path}")
    if runtime_state.configured_backend_context_size is not None:
        print(f"configured_backend_context_size: {runtime_state.configured_backend_context_size}")
    if runtime_state.configured_backend_predict_limit is not None:
        print(f"configured_backend_predict_limit: {runtime_state.configured_backend_predict_limit}")
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
    resolved_llmfit_binary = _resolve_llmfit_binary(args.project_root, args.llmfit_binary)
    report = inspect_host_environment(
        project_root=args.project_root,
        backend_root=args.backend_root,
        server_binary=args.server_binary,
        cli_binary=args.cli_binary,
        llmfit_binary=resolved_llmfit_binary,
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
    for tool in report.tool_checks:
        label = "ok" if tool["ok"] else "missing"
        detail = tool.get("executable_path") or ", ".join(tool.get("issues", [])) or "not available"
        print(f"tool: {tool['tool']} status={label} source={tool['source']} detail={detail}")
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

    resolved_llmfit_binary = _resolve_llmfit_binary(args.project_root, args.llmfit_binary)
    report = inspect_host_environment(
        project_root=args.project_root,
        backend_root=args.backend_root,
        server_binary=args.server_binary,
        cli_binary=args.cli_binary,
        llmfit_binary=resolved_llmfit_binary,
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
            acquisition = acquire_managed_llama_cpp_installation(
                args.project_root,
                report.acquisition_plan,
                jobs=args.jobs,
            )
            installation = acquisition.installation
            created = HostStateStore(args.project_root).save_backend_installation(installation)
            action = "acquired" if created else "updated"
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
        store = HostStateStore(args.project_root)
        result = validate_host_runtime(store, _service_config_from_args(args, store))
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


def handle_install_llmfit(args: argparse.Namespace) -> int:
    """Install llmfit into a normal user bin directory."""
    try:
        result = install_tool(
            args.project_root,
            "llmfit",
            user_bin_dir=normalize_user_bin_dir(args.user_bin_dir),
        )
    except (BootstrapError, HostStateError) as exc:
        return _exit_with_error(str(exc))
    return _print_tool_install_result(result, output_format=args.format)


def handle_install_hf(args: argparse.Namespace) -> int:
    """Install the Hugging Face CLI into a normal user bin directory."""
    try:
        result = install_tool(
            args.project_root,
            "hf",
            user_bin_dir=normalize_user_bin_dir(args.user_bin_dir),
        )
    except (BootstrapError, HostStateError) as exc:
        return _exit_with_error(str(exc))
    return _print_tool_install_result(result, output_format=args.format)


def handle_bootstrap(args: argparse.Namespace) -> int:
    """Prepare a clean host with operator tools and a managed backend."""
    payload: dict[str, object] = {
        "tool_installs": [],
    }
    try:
        user_bin_dir = normalize_user_bin_dir(args.user_bin_dir)
        for tool_name in ("llmfit", "hf"):
            tool_result = install_tool(args.project_root, tool_name, user_bin_dir=user_bin_dir)
            payload["tool_installs"].append(tool_result.to_dict())
        resolved_llmfit_binary = _resolve_llmfit_binary(args.project_root, args.llmfit_binary)
        report = inspect_host_environment(
            project_root=args.project_root,
            llmfit_binary=resolved_llmfit_binary,
        )
        payload["inspection"] = report.to_dict()
        if report.acquisition_plan is None:
            issues = "; ".join(report.hardware_detection.issues) or "hardware detection did not produce a backend acquisition plan"
            raise BootstrapError(issues)
        acquisition = acquire_managed_llama_cpp_installation(
            args.project_root,
            report.acquisition_plan,
            prebuilt_root=args.prebuilt_root,
            prebuilt_archive=args.prebuilt_archive,
            source_root=args.source_root,
            jobs=args.jobs,
        )
        created = HostStateStore(args.project_root).save_backend_installation(acquisition.installation)
        payload["backend"] = {
            "action": "acquired" if created else "updated",
            "installation": acquisition.installation.as_dict(),
            "acquisition": acquisition.to_dict(),
        }
        payload["next_steps"] = [
            "aistackd models install ...",
            "aistackd models activate <model>",
            "AISTACKD_API_KEY=... aistackd host start",
            "aistackd sync --write",
            "AISTACKD_REMOTE_API_KEY=... aistackd doctor ready --frontend opencode",
        ]
    except (BootstrapError, BackendAcquisitionError, HostStateError, ValueError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print("host bootstrap complete")
    for tool_payload in payload["tool_installs"]:
        print(f"{tool_payload['action']}: tool={tool_payload['tool']['tool']} path={tool_payload['tool']['executable_path']}")
    backend = payload["backend"]
    print(f"{backend['action']}: backend_root={backend['installation']['backend_root']}")
    print("next_steps:")
    for step in payload["next_steps"]:
        print(f"- {step}")
    return 0


def handle_serve(args: argparse.Namespace) -> int:
    """Run the local authenticated control-plane service."""
    try:
        store = HostStateStore(args.project_root)
        service = _service_config_from_args(args, store)
        result = validate_host_runtime(store, service)
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if not result.ok:
        for message in result.errors:
            print(message, file=sys.stderr)
        return 1

    existing_runtime = store.load_runtime_state()
    existing_control_plane = existing_runtime.control_plane_process
    if (
        existing_control_plane is not None
        and existing_runtime.control_plane_process_status in {"running", "starting"}
        and existing_control_plane.pid != os.getpid()
    ):
        return _exit_with_error(
            f"control-plane service is already active (pid={existing_control_plane.pid})"
        )

    try:
        running_process = launch_managed_backend_process(store, result.service)
    except (BackendProcessError, HostStateError) as exc:
        return _exit_with_error(str(exc))

    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    control_plane_record = save_current_control_plane_process(
        store,
        result.service,
        status="running",
        command=tuple(build_control_plane_command(args.project_root, result.service)),
        pid=os.getpid(),
    )
    stop_reason = "stopped"

    print("control plane serving")
    print(f"base_url: {result.service.base_url}")
    print(f"responses_base_url: {result.service.responses_base_url}")
    print(f"backend_base_url: {result.service.backend_base_url}")
    print(f"api_key_env: {result.service.api_key_env}")
    if result.runtime.backend_installation is not None:
        print(f"server_binary: {result.runtime.backend_installation.server_binary}")
    print(f"backend_pid: {running_process.record.pid}")
    print(f"backend_log_path: {running_process.record.log_path}")
    if running_process.record.context_size is not None:
        print(f"backend_context_size: {running_process.record.context_size}")
    if running_process.record.predict_limit is not None:
        print(f"backend_predict_limit: {running_process.record.predict_limit}")
    print(f"control_plane_pid: {control_plane_record.pid}")
    print(f"control_plane_log_path: {control_plane_record.log_path}")
    print(f"active_model: {result.runtime.active_model}")
    print("stop: Ctrl+C")
    try:
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        serve_control_plane(args.project_root, result.service)
    except KeyboardInterrupt:
        print("control plane stopped")
        return 0
    except ControlPlaneError as exc:
        stop_reason = "failed"
        return _exit_with_error(str(exc))
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        mark_current_control_plane_process_stopped(store, reason=stop_reason)
        stop_managed_backend_process(store, running_process)
    return 0


def handle_start(args: argparse.Namespace) -> int:
    """Start the managed control-plane service in the background."""
    try:
        store = HostStateStore(args.project_root)
        service = _service_config_from_args(args, store)
        result = validate_host_runtime(store, service)
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if not result.ok:
        for message in result.errors:
            print(message, file=sys.stderr)
        return 1

    try:
        running_process = launch_control_plane_process(args.project_root, result.service)
    except (ControlPlaneProcessError, HostStateError) as exc:
        return _exit_with_error(str(exc))

    payload = {
        "action": "started",
        "control_plane_process": running_process.record.as_dict(),
        "service": result.service.to_dict(),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print("managed control-plane started")
    print(f"control_plane_pid: {running_process.record.pid}")
    print(f"base_url: {result.service.base_url}")
    print(f"responses_base_url: {result.service.responses_base_url}")
    print(f"control_plane_log_path: {running_process.record.log_path}")
    return 0


def handle_stop(args: argparse.Namespace) -> int:
    """Stop the currently persisted managed backend process."""
    try:
        store = HostStateStore(args.project_root)
        runtime_before = store.load_runtime_state()
        if args.service or args.all:
            control_plane_record = stop_current_control_plane_process(store)
        else:
            control_plane_record = runtime_before.control_plane_process
        backend_record = stop_current_managed_backend_process(store) if not args.service or args.all else None
        runtime_after = store.load_runtime_state()
    except (BackendProcessError, ControlPlaneProcessError, HostStateError) as exc:
        return _exit_with_error(str(exc))

    stopped_backend = (
        runtime_before.backend_process_status in {"running", "starting"} and runtime_after.backend_process_status == "stopped"
    )
    stopped_service = (
        runtime_before.control_plane_process_status in {"running", "starting"}
        and runtime_after.control_plane_process_status == "stopped"
    )
    payload = {
        "action": (
            "stopped"
            if stopped_backend or stopped_service
            else "already_stopped"
        ),
        "before_status": runtime_before.backend_process_status,
        "after_status": runtime_after.backend_process_status,
        "backend_process": backend_record.as_dict() if backend_record is not None else None,
        "before_control_plane_status": runtime_before.control_plane_process_status,
        "after_control_plane_status": runtime_after.control_plane_process_status,
        "control_plane_process": control_plane_record.as_dict() if control_plane_record is not None else None,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    if stopped_service and stopped_backend and args.all:
        print("managed control-plane and backend stopped")
    elif stopped_service:
        print("managed control-plane stopped")
    elif stopped_backend:
        print("managed backend stopped")
    else:
        print("managed service/backend was not running")
    print(f"before_status: {payload['before_status']}")
    print(f"after_status: {payload['after_status']}")
    print(f"before_control_plane_status: {payload['before_control_plane_status']}")
    print(f"after_control_plane_status: {payload['after_control_plane_status']}")
    if backend_record is not None:
        print(f"backend_pid: {backend_record.pid}")
        print(f"backend_log_path: {backend_record.log_path}")
    if control_plane_record is not None:
        print(f"control_plane_pid: {control_plane_record.pid}")
        print(f"control_plane_log_path: {control_plane_record.log_path}")
    return 0


def handle_down(args: argparse.Namespace) -> int:
    """Stop both the managed control-plane and backend processes."""
    args.service = False
    args.all = True
    return handle_stop(args)


def handle_restart(args: argparse.Namespace) -> int:
    """Restart the managed backend process."""
    if args.service:
        return _handle_restart_service(args)

    try:
        store = HostStateStore(args.project_root)
        service = _service_config_from_args(args, store)
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
    if running_process.record.context_size is not None:
        print(f"backend_context_size: {running_process.record.context_size}")
    if running_process.record.predict_limit is not None:
        print(f"backend_predict_limit: {running_process.record.predict_limit}")
    print(f"active_model: {running_process.record.model}")
    return 0


def handle_logs(args: argparse.Namespace) -> int:
    """Print persisted host logs."""
    if args.lines < 1:
        return _exit_with_error("--lines must be at least 1")

    store = HostStateStore(args.project_root)
    if args.target == "backend":
        log_path = store.paths.backend_log_path()
    else:
        log_path = store.paths.control_plane_log_path()

    if not log_path.exists():
        return _exit_with_error(f"{args.target} log does not exist: {log_path}")

    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return _exit_with_error(str(exc))

    for line in lines[-args.lines :]:
        print(line)

    if not args.follow:
        return 0

    try:
        with log_path.open("r", encoding="utf-8") as handle:
            handle.seek(0, os.SEEK_END)
            while True:
                line = handle.readline()
                if line:
                    print(line, end="")
                    continue
                time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        return _exit_with_error(str(exc))


def handle_tune_show(args: argparse.Namespace) -> int:
    """Show the persisted backend tuning defaults."""
    store = HostStateStore(args.project_root)
    context_size, predict_limit = store.load_persisted_backend_tuning()
    source = "persisted" if context_size is not None and predict_limit is not None else "default"
    resolved_context_size = context_size or DEFAULT_BACKEND_CONTEXT_SIZE
    resolved_predict_limit = predict_limit or DEFAULT_BACKEND_PREDICT_LIMIT
    payload = {
        "backend_context_size": resolved_context_size,
        "backend_predict_limit": resolved_predict_limit,
        "source": source,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print("host tuning")
    print(f"backend_context_size: {resolved_context_size}")
    print(f"backend_predict_limit: {resolved_predict_limit}")
    print(f"source: {source}")
    return 0


def handle_tune_set(args: argparse.Namespace) -> int:
    """Persist backend tuning defaults."""
    if args.backend_context_size is None and args.backend_predict_limit is None:
        return _exit_with_error("specify at least one tuning flag to persist")

    store = HostStateStore(args.project_root)
    current_context_size, current_predict_limit = store.load_persisted_backend_tuning()
    resolved_context_size = (
        args.backend_context_size
        if args.backend_context_size is not None
        else current_context_size or DEFAULT_BACKEND_CONTEXT_SIZE
    )
    resolved_predict_limit = (
        args.backend_predict_limit
        if args.backend_predict_limit is not None
        else current_predict_limit or DEFAULT_BACKEND_PREDICT_LIMIT
    )
    if resolved_context_size < 1:
        return _exit_with_error("backend_context_size must be a positive integer")
    if resolved_predict_limit < 1:
        return _exit_with_error("backend_predict_limit must be a positive integer")
    context_size, predict_limit = store.save_persisted_backend_tuning(
        context_size=resolved_context_size,
        predict_limit=resolved_predict_limit,
    )
    payload = {
        "action": "updated",
        "backend_context_size": context_size,
        "backend_predict_limit": predict_limit,
        "source": "persisted",
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print("updated host tuning")
    print(f"backend_context_size: {context_size}")
    print(f"backend_predict_limit: {predict_limit}")
    return 0


def handle_tune_reset(args: argparse.Namespace) -> int:
    """Reset persisted backend tuning defaults to the documented runtime defaults."""
    store = HostStateStore(args.project_root)
    store.reset_persisted_backend_tuning()
    payload = {
        "action": "reset",
        "backend_context_size": DEFAULT_BACKEND_CONTEXT_SIZE,
        "backend_predict_limit": DEFAULT_BACKEND_PREDICT_LIMIT,
        "source": "default",
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print("reset host tuning")
    print(f"backend_context_size: {DEFAULT_BACKEND_CONTEXT_SIZE}")
    print(f"backend_predict_limit: {DEFAULT_BACKEND_PREDICT_LIMIT}")
    return 0


def _handle_restart_service(args: argparse.Namespace) -> int:
    try:
        store = HostStateStore(args.project_root)
        service = _service_config_from_args(args, store)
        result = validate_host_runtime(store, service)
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if not result.ok:
        for message in result.errors:
            print(message, file=sys.stderr)
        return 1

    before_status = result.runtime.control_plane_process_status
    try:
        stop_current_control_plane_process(store)
        running_process = launch_control_plane_process(args.project_root, result.service)
    except (ControlPlaneProcessError, HostStateError) as exc:
        return _exit_with_error(str(exc))

    payload = {
        "action": "restarted" if before_status in {"running", "starting"} else "started",
        "before_control_plane_status": before_status,
        "after_control_plane_status": "starting",
        "control_plane_process": running_process.record.as_dict(),
        "service": result.service.to_dict(),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"managed control-plane {payload['action']}")
    print(f"before_control_plane_status: {payload['before_control_plane_status']}")
    print(f"after_control_plane_status: {payload['after_control_plane_status']}")
    print(f"control_plane_pid: {running_process.record.pid}")
    print(f"base_url: {result.service.base_url}")
    print(f"control_plane_log_path: {running_process.record.log_path}")
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


def _add_user_bin_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--user-bin-dir",
        type=Path,
        default=DEFAULT_USER_BIN_DIR,
        help=f"user bin directory for bootstrap-installed operator tools (default: {DEFAULT_USER_BIN_DIR})",
    )


def _add_tuning_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend-context-size",
        type=int,
        default=None,
        help=(
            "context size for the managed llama.cpp process "
            f"(default: saved value or {DEFAULT_BACKEND_CONTEXT_SIZE})"
        ),
    )
    parser.add_argument(
        "--backend-predict-limit",
        type=int,
        default=None,
        help=(
            "token prediction limit for the managed llama.cpp process "
            f"(default: saved value or {DEFAULT_BACKEND_PREDICT_LIMIT})"
        ),
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
    parser.add_argument(
        "--backend-context-size",
        type=int,
        default=None,
        help=(
            "context size for the managed llama.cpp process "
            f"(default: saved value or {DEFAULT_BACKEND_CONTEXT_SIZE})"
        ),
    )
    parser.add_argument(
        "--backend-predict-limit",
        type=int,
        default=None,
        help=(
            "token prediction limit for the managed llama.cpp process "
            f"(default: saved value or {DEFAULT_BACKEND_PREDICT_LIMIT})"
        ),
    )


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )


def _service_config_from_args(
    args: argparse.Namespace,
    store: HostStateStore | None = None,
) -> HostServiceConfig:
    persisted_context_size: int | None = None
    persisted_predict_limit: int | None = None
    if store is not None and hasattr(store, "load_persisted_backend_tuning"):
        persisted_context_size, persisted_predict_limit = store.load_persisted_backend_tuning()
    return HostServiceConfig(
        bind_host=args.bind_host,
        port=args.port,
        api_key_env=args.api_key_env,
        backend_bind_host=args.backend_bind_host,
        backend_port=args.backend_port,
        backend_context_size=(
            args.backend_context_size
            if args.backend_context_size is not None
            else persisted_context_size or DEFAULT_BACKEND_CONTEXT_SIZE
        ),
        backend_predict_limit=(
            args.backend_predict_limit
            if args.backend_predict_limit is not None
            else persisted_predict_limit or DEFAULT_BACKEND_PREDICT_LIMIT
        ),
    ).normalized()


def _exit_with_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _resolve_llmfit_binary(project_root: Path, requested_binary: str) -> str:
    try:
        return resolve_tool_binary(project_root, "llmfit", requested=requested_binary)
    except BootstrapError:
        return requested_binary


def _print_tool_install_result(result: object, *, output_format: str) -> int:
    payload = result.to_dict()
    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return 0
    print(f"{payload['action']} tool '{payload['tool']['tool']}'")
    print(f"path: {payload['tool']['executable_path']}")
    print(f"version: {payload['tool']['version']}")
    return 0


def _raise_keyboard_interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt()
