"""Server runtime state helpers (PID files + process controls)."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Optional


def runtime_dir(project_root: Path) -> Path:
    return project_root / ".ai_stack"


def server_pid_path(project_root: Path) -> Path:
    return runtime_dir(project_root) / "server.pid"


def load_server_pid(project_root: Path) -> Optional[dict]:
    pid_path = server_pid_path(project_root)
    if not pid_path.exists():
        return None
    try:
        return json.loads(pid_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_server_pid(project_root: Path, endpoint: str, pid: int, model_path: str) -> None:
    dir_path = runtime_dir(project_root)
    dir_path.mkdir(parents=True, exist_ok=True)
    server_pid_path(project_root).write_text(
        json.dumps(
            {
                "pid": pid,
                "model_path": model_path,
                "endpoint": endpoint,
                "started_at": int(time.time()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_server_pid(project_root: Path) -> None:
    pid_path = server_pid_path(project_root)
    if pid_path.exists():
        pid_path.unlink()


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def terminate_process(pid: int, timeout_seconds: float = 8.0) -> bool:
    if not is_process_running(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    time.sleep(0.2)
    return not is_process_running(pid)


__all__ = [
    "clear_server_pid",
    "is_process_running",
    "load_server_pid",
    "runtime_dir",
    "server_pid_path",
    "terminate_process",
    "write_server_pid",
]
