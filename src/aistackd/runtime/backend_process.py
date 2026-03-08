"""Managed backend-process launch and supervision helpers."""

from __future__ import annotations

import subprocess
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aistackd.models.sources import PRIMARY_BACKEND
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostBackendProcess, HostStateStore

DEFAULT_BACKEND_STARTUP_GRACE_SECONDS = 0.05
DEFAULT_BACKEND_STOP_TIMEOUT_SECONDS = 1.0
DEFAULT_BACKEND_STOP_POLL_SECONDS = 0.05


@dataclass(frozen=True)
class BackendLaunchPlan:
    """Launch plan for one managed backend process."""

    backend: str
    command: tuple[str, ...]
    bind_host: str
    port: int
    model: str
    artifact_path: str
    server_binary: str
    log_path: str

    @property
    def base_url(self) -> str:
        """Return the internal backend URL for this launch."""
        return f"http://{self.bind_host}:{self.port}"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "backend": self.backend,
            "command": list(self.command),
            "bind_host": self.bind_host,
            "port": self.port,
            "base_url": self.base_url,
            "model": self.model,
            "artifact_path": self.artifact_path,
            "server_binary": self.server_binary,
            "log_path": self.log_path,
        }


@dataclass
class RunningBackendProcess:
    """Live backend-process handle paired with its persisted record."""

    plan: BackendLaunchPlan
    record: HostBackendProcess
    process: subprocess.Popen[str]


class BackendProcessError(RuntimeError):
    """Raised when the managed backend process cannot be launched or stopped cleanly."""


def build_backend_launch_plan(store: HostStateStore, service: HostServiceConfig) -> BackendLaunchPlan:
    """Build the launch plan for the active backend installation and active model artifact."""
    runtime = store.load_runtime_state()
    if runtime.backend_installation is None:
        raise BackendProcessError("no backend installation is configured for host runtime")
    if runtime.active_model is None:
        raise BackendProcessError("no active model is configured for host runtime")
    if runtime.activation_state != "ready":
        raise BackendProcessError(
            f"active model '{runtime.active_model}' is not ready for serving "
            f"(activation_state={runtime.activation_state})"
        )

    active_record = next((record for record in runtime.installed_models if record.model == runtime.active_model), None)
    if active_record is None:
        raise BackendProcessError(f"active model '{runtime.active_model}' is not installed")

    normalized_service = service.normalized()
    log_path = store.paths.backend_log_path(runtime.backend)
    command = (
        runtime.backend_installation.server_binary,
        "--model",
        active_record.artifact_path,
        "--host",
        normalized_service.backend_bind_host,
        "--port",
        str(normalized_service.backend_port),
    )
    return BackendLaunchPlan(
        backend=runtime.backend,
        command=command,
        bind_host=normalized_service.backend_bind_host,
        port=normalized_service.backend_port,
        model=active_record.model,
        artifact_path=active_record.artifact_path,
        server_binary=runtime.backend_installation.server_binary,
        log_path=str(log_path),
    )


def launch_managed_backend_process(
    store: HostStateStore,
    service: HostServiceConfig,
) -> RunningBackendProcess:
    """Launch the managed backend process and persist its running state."""
    runtime = store.load_runtime_state()
    if runtime.backend_process_status in {"running", "starting"} and runtime.backend_process is not None:
        raise BackendProcessError(
            f"backend process is already active for model '{runtime.backend_process.model}' "
            f"(pid={runtime.backend_process.pid})"
        )

    plan = build_backend_launch_plan(store, service)
    log_path = Path(plan.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = _timestamp_now()

    with log_path.open("w", encoding="utf-8") as log_handle:
        try:
            process = subprocess.Popen(
                list(plan.command),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            raise BackendProcessError(f"failed to launch backend process: {exc}") from exc

    starting_record = HostBackendProcess(
        backend=plan.backend,
        status="starting",
        pid=process.pid,
        command=plan.command,
        bind_host=plan.bind_host,
        port=plan.port,
        model=plan.model,
        artifact_path=plan.artifact_path,
        server_binary=plan.server_binary,
        log_path=plan.log_path,
        started_at=started_at,
    )
    _save_backend_process_if_current(store, starting_record, expected_pid=process.pid)

    time.sleep(DEFAULT_BACKEND_STARTUP_GRACE_SECONDS)
    exit_code = process.poll()
    if exit_code is not None:
        failed_record = HostBackendProcess(
            backend=plan.backend,
            status="failed",
            pid=process.pid,
            command=plan.command,
            bind_host=plan.bind_host,
            port=plan.port,
            model=plan.model,
            artifact_path=plan.artifact_path,
            server_binary=plan.server_binary,
            log_path=plan.log_path,
            started_at=started_at,
            stopped_at=_timestamp_now(),
            exit_code=exit_code,
        )
        _save_backend_process_if_current(store, failed_record, expected_pid=process.pid)
        raise BackendProcessError(
            f"backend process exited immediately with code {exit_code}; see '{plan.log_path}'"
        )

    running_record = HostBackendProcess(
        backend=plan.backend,
        status="running",
        pid=process.pid,
        command=plan.command,
        bind_host=plan.bind_host,
        port=plan.port,
        model=plan.model,
        artifact_path=plan.artifact_path,
        server_binary=plan.server_binary,
        log_path=plan.log_path,
        started_at=started_at,
    )
    _save_backend_process_if_current(store, running_record, expected_pid=process.pid)
    return RunningBackendProcess(plan=plan, record=running_record, process=process)


def stop_managed_backend_process(
    store: HostStateStore,
    running_process: RunningBackendProcess,
    *,
    reason: str = "stopped",
) -> HostBackendProcess:
    """Stop one running managed backend process and persist the terminal state."""
    process = running_process.process
    exit_code = process.poll()

    if exit_code is None:
        process.terminate()
        try:
            exit_code = process.wait(timeout=DEFAULT_BACKEND_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            exit_code = process.wait(timeout=DEFAULT_BACKEND_STOP_TIMEOUT_SECONDS)

    status = reason if reason in {"stopped", "failed"} else "stopped"
    if status != "failed" and process.poll() not in (None, -15) and exit_code not in (0, None):
        status = "exited"

    stopped_record = HostBackendProcess(
        backend=running_process.record.backend,
        status=status,
        pid=running_process.record.pid,
        command=running_process.record.command,
        bind_host=running_process.record.bind_host,
        port=running_process.record.port,
        model=running_process.record.model,
        artifact_path=running_process.record.artifact_path,
        server_binary=running_process.record.server_binary,
        log_path=running_process.record.log_path,
        started_at=running_process.record.started_at,
        stopped_at=_timestamp_now(),
        exit_code=exit_code,
    )
    return _save_backend_process_if_current(
        store,
        stopped_record,
        expected_pid=running_process.record.pid,
    )


def stop_current_managed_backend_process(
    store: HostStateStore,
    *,
    reason: str = "stopped",
) -> HostBackendProcess | None:
    """Stop the currently persisted managed backend process if it is still active."""
    runtime = store.load_runtime_state()
    current = runtime.backend_process
    if current is None:
        return None
    if current.status not in {"running", "starting"}:
        return current

    exit_code = _terminate_pid(current.pid)
    status = "failed" if reason == "failed" else "stopped"
    stopped_record = HostBackendProcess(
        backend=current.backend,
        status=status,
        pid=current.pid,
        command=current.command,
        bind_host=current.bind_host,
        port=current.port,
        model=current.model,
        artifact_path=current.artifact_path,
        server_binary=current.server_binary,
        log_path=current.log_path,
        started_at=current.started_at,
        stopped_at=_timestamp_now(),
        exit_code=exit_code,
    )
    return _save_backend_process_if_current(store, stopped_record, expected_pid=current.pid)


def restart_managed_backend_process(
    store: HostStateStore,
    service: HostServiceConfig,
) -> RunningBackendProcess:
    """Restart the managed backend process using the current host runtime state."""
    stop_current_managed_backend_process(store)
    return launch_managed_backend_process(store, service)


def _save_backend_process_if_current(
    store: HostStateStore,
    record: HostBackendProcess,
    *,
    expected_pid: int,
) -> HostBackendProcess:
    current_record = store.load_backend_process()
    if (
        current_record is not None
        and current_record.pid != expected_pid
        and current_record.status in {"starting", "running"}
    ):
        return current_record
    store.save_backend_process(record)
    return record


def _terminate_pid(pid: int) -> int | None:
    if pid < 1 or not _pid_exists(pid):
        return None
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return None
    except PermissionError as exc:
        raise BackendProcessError(f"permission denied while stopping backend pid {pid}") from exc

    deadline = time.monotonic() + DEFAULT_BACKEND_STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return -int(signal.SIGTERM)
        time.sleep(DEFAULT_BACKEND_STOP_POLL_SECONDS)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return -int(signal.SIGTERM)
    except PermissionError as exc:
        raise BackendProcessError(f"permission denied while killing backend pid {pid}") from exc

    deadline = time.monotonic() + DEFAULT_BACKEND_STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return -int(signal.SIGKILL)
        time.sleep(DEFAULT_BACKEND_STOP_POLL_SECONDS)
    raise BackendProcessError(f"backend pid {pid} did not exit after SIGTERM/SIGKILL")


def _pid_exists(pid: int) -> bool:
    if pid < 1:
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
