"""Run ai_stack commands with: python -m ai_stack <command> ..."""

from __future__ import annotations

import argparse
import sys

from ai_stack.cli import (
    check_deps_cli,
    download_model_cli,
    setup_cli,
    sync_openhands_config_cli,
    sync_opencode_config_cli,
    start_server_cli,
    status_cli,
    stop_server_cli,
    uninstall_cli,
)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="ai_stack command runner")
    parser.add_argument(
        "command",
        choices=[
            "setup-stack",
            "server-start",
            "server-status",
            "server-stop",
            "download-model",
            "check-deps",
            "uninstall-stack",
            "sync-openhands-config",
            "sync-opencode-config",
        ],
        help="Command to run",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for command")
    parsed = parser.parse_args(argv)

    command_map = {
        "setup-stack": setup_cli,
        "server-start": start_server_cli,
        "server-status": status_cli,
        "server-stop": stop_server_cli,
        "download-model": download_model_cli,
        "check-deps": check_deps_cli,
        "uninstall-stack": uninstall_cli,
        "sync-openhands-config": sync_openhands_config_cli,
        "sync-opencode-config": sync_opencode_config_cli,
    }

    fn = command_map[parsed.command]
    if parsed.command in {"server-stop", "uninstall-stack", "sync-opencode-config", "sync-openhands-config"}:
        return fn(parsed.args)

    old_argv = sys.argv
    try:
        sys.argv = [f"ai_stack {parsed.command}"] + parsed.args
        return fn()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    main()
