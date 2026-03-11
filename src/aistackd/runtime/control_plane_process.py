"""Managed control-plane service launch and shutdown helpers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostControlPlaneProcess, HostStateStore

DEFAULT_CONTROL_PLANE_STARTUP_GRACE_SECONDS = 0.05
DEFAULT_CONTROL_PLANE_STOP_TIMEOUT_SECONDS = 1.0
DEFAULT_CONTROL_PLANE_STOP_POLL_SECONDS = 0.05


@dataclass
class RunningControlPlaneProcess:
    """Live control-plane process handle paired with its persisted record."""

    record: HostControlPlaneProcess
    process: subprocess.Popen[str]


class ControlPlaneProcessError(RuntimeError):
    """Raised when the managed control-plane process cannot be launched or stopped cleanly."""


def launch_control_plane_process(
    project_root: Path,
    service: HostServiceConfig,
) -> RunningControlPlaneProcess:
    """Launch the managed control-plane service in the background."""
    store = HostStateStore(project_root)
    runtime = store.load_runtime_state()
    if runtime.control_plane_process_status in {"running", "starting"} and runtime.control_plane_process is not None:
        raise ControlPlaneProcessError(
            f"control-plane service is already active (pid={runtime.control_plane_process.pid})"
        )

    normalized_service = service.normalized()
    command = build_control_plane_command(project_root, normalized_service)
    log_path = store.paths.control_plane_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = _timestamp_now()

    with log_path.open("w", encoding="utf-8") as log_handle:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise ControlPlaneProcessError(f"failed to launch control-plane service: {exc}") from exc

    starting_record = HostControlPlaneProcess(
        status="starting",
        pid=process.pid,
        command=tuple(command),
        bind_host=normalized_service.bind_host,
        port=normalized_service.port,
        log_path=str(log_path),
        started_at=started_at,
    )
    store.save_control_plane_process(starting_record)

    time.sleep(DEFAULT_CONTROL_PLANE_STARTUP_GRACE_SECONDS)
    exit_code = process.poll()
    if exit_code is not None:
        failed_record = HostControlPlaneProcess(
            status="failed",
            pid=process.pid,
            command=tuple(command),
            bind_host=normalized_service.bind_host,
            port=normalized_service.port,
            log_path=str(log_path),
            started_at=started_at,
            stopped_at=_timestamp_now(),
            exit_code=exit_code,
        )
        store.save_control_plane_process(failed_record)
        raise ControlPlaneProcessError(
            f"control-plane service exited immediately with code {exit_code}; see '{log_path}'"
        )

    return RunningControlPlaneProcess(record=starting_record, process=process)


def stop_current_control_plane_process(store: HostStateStore) -> HostControlPlaneProcess | None:
    """Stop the current managed control-plane service if it is active."""
    current = store.load_control_plane_process()
    if current is None:
        return None
    if current.status not in {"running", "starting"}:
        return current

    exit_code = _terminate_pid(current.pid)
    stopped_record = HostControlPlaneProcess(
        status="stopped",
        pid=current.pid,
        command=current.command,
        bind_host=current.bind_host,
        port=current.port,
        log_path=current.log_path,
        started_at=current.started_at,
        stopped_at=_timestamp_now(),
        exit_code=exit_code,
    )
    store.save_control_plane_process(stopped_record)
    return stopped_record


def save_current_control_plane_process(
    store: HostStateStore,
    service: HostServiceConfig,
    *,
    status: str,
    command: tuple[str, ...],
    pid: int | None = None,
) -> HostControlPlaneProcess:
    """Persist the current process as the managed control-plane service."""
    normalized_service = service.normalized()
    record = HostControlPlaneProcess(
        status=status,
        pid=os.getpid() if pid is None else pid,
        command=command,
        bind_host=normalized_service.bind_host,
        port=normalized_service.port,
        log_path=str(store.paths.control_plane_log_path()),
        started_at=_timestamp_now(),
    )
    store.save_control_plane_process(record)
    return record


def mark_current_control_plane_process_stopped(
    store: HostStateStore,
    *,
    reason: str,
    exit_code: int | None = None,
) -> HostControlPlaneProcess | None:
    """Mark the current managed control-plane process as stopped or failed."""
    current = store.load_control_plane_process()
    if current is None:
        return None
    status = reason if reason in {"stopped", "failed"} else "stopped"
    record = HostControlPlaneProcess(
        status=status,
        pid=current.pid,
        command=current.command,
        bind_host=current.bind_host,
        port=current.port,
        log_path=current.log_path,
        started_at=current.started_at,
        stopped_at=_timestamp_now(),
        exit_code=exit_code,
    )
    store.save_control_plane_process(record)
    return record


def build_control_plane_command(project_root: Path, service: HostServiceConfig) -> list[str]:
    return [
        sys.executable,
        "-m",
        "aistackd",
        "host",
        "serve",
        "--project-root",
        str(project_root.resolve()),
        "--bind-host",
        service.bind_host,
        "--port",
        str(service.port),
        "--api-key-env",
        service.api_key_env,
        "--backend-bind-host",
        service.backend_bind_host,
        "--backend-port",
        str(service.backend_port),
        "--backend-context-size",
        str(service.backend_context_size),
        "--backend-predict-limit",
        str(service.backend_predict_limit),
    ]


def _terminate_pid(pid: int) -> int | None:
    if pid < 1 or not _pid_exists(pid):
        return None
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return None
    except PermissionError as exc:
        raise ControlPlaneProcessError(f"permission denied while stopping control-plane pid {pid}") from exc

    deadline = time.monotonic() + DEFAULT_CONTROL_PLANE_STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return -int(signal.SIGTERM)
        time.sleep(DEFAULT_CONTROL_PLANE_STOP_POLL_SECONDS)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return -int(signal.SIGTERM)
    except PermissionError as exc:
        raise ControlPlaneProcessError(f"permission denied while killing control-plane pid {pid}") from exc

    deadline = time.monotonic() + DEFAULT_CONTROL_PLANE_STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return -int(signal.SIGKILL)
        time.sleep(DEFAULT_CONTROL_PLANE_STOP_POLL_SECONDS)
    raise ControlPlaneProcessError(f"control-plane pid {pid} did not exit after SIGTERM/SIGKILL")


def _pid_exists(pid: int) -> bool:
    if pid < 1:
        return False
    stat_path = Path("/proc") / str(pid) / "stat"
    if stat_path.exists():
        try:
            stat_fields = stat_path.read_text(encoding="utf-8").split()
        except OSError:
            stat_fields = ()
        if len(stat_fields) >= 3 and stat_fields[2] == "Z":
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _timestamp_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
