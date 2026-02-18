"""ai_stack CLI package with backward-compatible entrypoint exports."""

from ai_stack.core.config import config
from ai_stack.stack.manager import SetupManager

from ai_stack.cli.download import download_model_cli
from ai_stack.cli.server import (
    _clear_server_pid,
    _is_process_running,
    _load_server_pid,
    _runtime_dir,
    _server_pid_path,
    _start_detached_server,
    _start_foreground_server,
    _terminate_process,
    _write_server_pid,
    start_server_cli,
    status_cli,
    stop_server_cli,
)
from ai_stack.cli.setup import check_deps_cli, setup_cli, uninstall_cli

__all__ = [
    "SetupManager",
    "check_deps_cli",
    "config",
    "download_model_cli",
    "setup_cli",
    "start_server_cli",
    "status_cli",
    "stop_server_cli",
    "uninstall_cli",
    "_clear_server_pid",
    "_is_process_running",
    "_load_server_pid",
    "_runtime_dir",
    "_server_pid_path",
    "_start_detached_server",
    "_start_foreground_server",
    "_terminate_process",
    "_write_server_pid",
]
