"""Managed backend-process launch and supervision helpers."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aistackd.models.sources import PRIMARY_BACKEND
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostBackendProcess, HostStateStore

DEFAULT_BACKEND_STARTUP_GRACE_SECONDS = 0.05
DEFAULT_BACKEND_STOP_TIMEOUT_SECONDS = 1.0


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
    if runtime.backend_process_status == "running" and runtime.backend_process is not None:
        raise BackendProcessError(
            f"backend process is already running for model '{runtime.backend_process.model}' "
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
        store.save_backend_process(failed_record)
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
    store.save_backend_process(running_record)
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
    store.save_backend_process(stopped_record)
    return stopped_record


def _timestamp_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
