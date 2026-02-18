"""Server-related CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ai_stack.core.config import config
from ai_stack.core.errors import exit_with_error, exit_with_unexpected_error
from ai_stack.core.exceptions import AiStackError
from ai_stack.core.logging import emit_event
from ai_stack.llm import create_client
from ai_stack.stack.manager import SetupManager

from ai_stack.cli.main import extract_context_size, print_bullet_list, print_cli_header, print_section
from ai_stack.cli import server_runtime
from ai_stack.cli import server_start as server_start_cmd
from ai_stack.cli import server_status as server_status_cmd
from ai_stack.cli import server_stop as server_stop_cmd


def _runtime_dir() -> Path:
    return server_runtime.runtime_dir(config.paths.project_root)


def _server_pid_path() -> Path:
    return server_runtime.server_pid_path(config.paths.project_root)


def _load_server_pid() -> Optional[dict]:
    return server_runtime.load_server_pid(config.paths.project_root)


def _write_server_pid(pid: int, model_path: str) -> None:
    server_runtime.write_server_pid(
        project_root=config.paths.project_root,
        endpoint=config.server.llama_url,
        pid=pid,
        model_path=model_path,
    )


def _clear_server_pid() -> None:
    server_runtime.clear_server_pid(config.paths.project_root)


def _is_process_running(pid: int) -> bool:
    return server_runtime.is_process_running(pid)


def _terminate_process(pid: int, timeout_seconds: float = 8.0) -> bool:
    return server_runtime.terminate_process(pid, timeout_seconds=timeout_seconds)


def start_server_cli():
    """CLI for starting the server."""
    try:
        server_start_cmd.start_server_cli(
            config=config,
            setup_manager_cls=SetupManager,
            exit_with_error=exit_with_error,
            ai_stack_error_cls=AiStackError,
            start_detached_fn=_start_detached_server,
            start_foreground_fn=_start_foreground_server,
            print_section=print_section,
            print_bullet_list=print_bullet_list,
        )
    except Exception as exc:
        emit_event("cli.server_start.wrapper.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="Server start", exc=exc)


def _start_detached_server(manager, model_path: str):
    """Start server in background."""
    server_start_cmd.start_detached_server(
        config=config,
        load_server_pid_fn=_load_server_pid,
        is_process_running_fn=_is_process_running,
        clear_server_pid_fn=_clear_server_pid,
        write_server_pid_fn=_write_server_pid,
        manager=manager,
        model_path=model_path,
        print_section=print_section,
    )


def _start_foreground_server(manager, model_path: str):
    """Start server in foreground."""
    server_start_cmd.start_foreground_server(
        config=config,
        manager=manager,
        model_path=model_path,
        print_section=print_section,
    )


def status_cli():
    """CLI for checking status."""
    try:
        server_status_cmd.status_cli(
            config=config,
            create_client=create_client,
            extract_context_size=extract_context_size,
            print_cli_header=print_cli_header,
            print_section=print_section,
        )
    except Exception as exc:
        emit_event("cli.server_status.wrapper.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="Server status", exc=exc)


def stop_server_cli(argv=None):
    """CLI for stopping the server."""
    try:
        server_stop_cmd.stop_server_cli(
            load_server_pid_fn=_load_server_pid,
            is_process_running_fn=_is_process_running,
            terminate_process_fn=_terminate_process,
            clear_server_pid_fn=_clear_server_pid,
            exit_with_error=exit_with_error,
            argv=argv,
        )
    except Exception as exc:
        emit_event("cli.server_stop.wrapper.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="Server stop", exc=exc)


__all__ = [
    "start_server_cli",
    "status_cli",
    "stop_server_cli",
    "_start_detached_server",
    "_start_foreground_server",
    "_runtime_dir",
    "_server_pid_path",
    "_load_server_pid",
    "_write_server_pid",
    "_clear_server_pid",
    "_is_process_running",
    "_terminate_process",
]
