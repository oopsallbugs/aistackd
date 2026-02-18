"""Stop command logic for server CLI."""

from __future__ import annotations

import argparse
from typing import Callable, Optional, Protocol

from ai_stack.core.logging import emit_event


class _ExitWithErrorLike(Protocol):
    def __call__(self, *, message: str, detail: Optional[str] = None) -> None: ...


def stop_server_cli(
    *,
    load_server_pid_fn: Callable[[], Optional[dict]],
    is_process_running_fn: Callable[[int], bool],
    terminate_process_fn: Callable[[int], bool],
    clear_server_pid_fn: Callable[[], None],
    exit_with_error: _ExitWithErrorLike,
    argv=None,
):
    """CLI for stopping the server."""
    emit_event("cli.server_stop.start")
    parser = argparse.ArgumentParser(description="Stop detached AI Stack server")
    parser.parse_args(argv)

    print("🛑 Stopping AI Stack server...")

    pid_record = load_server_pid_fn()
    if not pid_record:
        emit_event("cli.server_stop.skipped", reason="pid_missing")
        print("ℹ️  No managed detached server found (missing PID file).")
        return

    try:
        pid = int(pid_record.get("pid", 0))
    except (TypeError, ValueError):
        pid = 0

    if not is_process_running_fn(pid):
        emit_event("cli.server_stop.stale_pid", pid=pid)
        print("ℹ️  PID file exists but process is not running. Cleaning up stale state.")
        clear_server_pid_fn()
        return

    print(f"  Stopping PID {pid}...")
    if terminate_process_fn(pid):
        clear_server_pid_fn()
        print("✅ Server stopped")
        emit_event("cli.server_stop.complete", ok=True, pid=pid)
        return

    emit_event("cli.server_stop.failed", level="error", pid=pid)
    exit_with_error(message=f"Failed to stop PID {pid}")


__all__ = ["stop_server_cli"]
