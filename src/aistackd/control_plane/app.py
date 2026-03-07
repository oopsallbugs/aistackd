"""Minimal control-plane HTTP server."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from aistackd.control_plane import HEALTH_ENDPOINT, MODELS_ENDPOINT, RESPONSES_ENDPOINT
from aistackd.control_plane.responses import (
    ResponsesProxyError,
    is_streaming_request,
    open_responses_stream,
    parse_json_request_body,
    proxy_responses_request,
)
from aistackd.runtime.host import HostServiceConfig, resolve_api_key
from aistackd.state.files import load_json_object
from aistackd.state.host import HostStateStore


class ControlPlaneError(RuntimeError):
    """Raised when the control plane cannot start or serve correctly."""


class ControlPlaneServer(ThreadingHTTPServer):
    """HTTP server carrying repo-owned control-plane dependencies."""

    store: HostStateStore
    service_config: HostServiceConfig
    api_key: str


class ControlPlaneRequestHandler(BaseHTTPRequestHandler):
    """Serve repo-owned control-plane endpoints."""

    server_version = "aistackd-control-plane/0.1"

    def do_GET(self) -> None:  # noqa: N802
        server = cast(ControlPlaneServer, self.server)
        path = urlsplit(self.path).path

        if not self._is_authorized(server.api_key):
            self._write_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": {"message": "missing or invalid API key", "type": "authentication_error"}},
                extra_headers={"WWW-Authenticate": 'Bearer realm="aistackd"'},
            )
            return

        if path == HEALTH_ENDPOINT:
            self._handle_health(server)
            return
        if path == MODELS_ENDPOINT:
            self._handle_models(server)
            return

        self._write_json(
            HTTPStatus.NOT_FOUND,
            {"error": {"message": f"unknown path '{path}'", "type": "invalid_request_error"}},
        )

    def do_POST(self) -> None:  # noqa: N802
        server = cast(ControlPlaneServer, self.server)
        path = urlsplit(self.path).path

        if not self._is_authorized(server.api_key):
            self._write_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": {"message": "missing or invalid API key", "type": "authentication_error"}},
                extra_headers={"WWW-Authenticate": 'Bearer realm="aistackd"'},
            )
            return

        if path == RESPONSES_ENDPOINT:
            self._handle_responses(server)
            return

        self._write_json(
            HTTPStatus.NOT_FOUND,
            {"error": {"message": f"unknown path '{path}'", "type": "invalid_request_error"}},
        )

    def log_message(self, format: str, *args: object) -> None:
        """Suppress stdlib request logging for deterministic CLI/test output."""
        return

    def _handle_health(self, server: ControlPlaneServer) -> None:
        runtime = server.store.load_runtime_state()
        status = (
            "ok"
            if runtime.activation_state == "ready" and runtime.backend_process_status == "running"
            else "degraded"
        )
        http_status = HTTPStatus.OK if status == "ok" else HTTPStatus.SERVICE_UNAVAILABLE
        self._write_json(
            http_status,
            {
                "status": status,
                "backend": runtime.backend,
                "backend_status": runtime.backend_status,
                "backend_process_status": runtime.backend_process_status,
                "active_model": runtime.active_model,
                "active_source": runtime.active_source,
                "activation_state": runtime.activation_state,
                "installed_model_count": len(runtime.installed_models),
                "base_url": server.service_config.base_url,
                "responses_base_url": server.service_config.responses_base_url,
                "backend_base_url": server.service_config.backend_base_url,
                "server_binary": (
                    runtime.backend_installation.server_binary
                    if runtime.backend_installation is not None
                    else None
                ),
                "backend_process": (
                    runtime.backend_process.as_dict()
                    if runtime.backend_process is not None
                    else None
                ),
            },
        )

    def _handle_models(self, server: ControlPlaneServer) -> None:
        runtime = server.store.load_runtime_state()
        payload = {
            "object": "list",
            "active_model": runtime.active_model,
            "data": [_model_payload(record, runtime.active_model) for record in runtime.installed_models],
        }
        self._write_json(HTTPStatus.OK, payload)

    def _handle_responses(self, server: ControlPlaneServer) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"error": {"message": "Content-Length must be a valid integer", "type": "invalid_request_error"}},
            )
            return

        request_body = self.rfile.read(max(content_length, 0))
        try:
            request_payload = parse_json_request_body(request_body)
            if is_streaming_request(request_payload):
                stream_session = open_responses_stream(server.store, server.service_config, request_payload)
            else:
                response_payload = proxy_responses_request(server.store, server.service_config, request_payload)
        except ResponsesProxyError as exc:
            self._write_json(exc.status, exc.to_payload())
            return

        if is_streaming_request(request_payload):
            try:
                self._write_sse_headers()
                for event in stream_session.iter_events():
                    self._write_sse_event(event)
            except OSError:
                return
            finally:
                stream_session.close()
            return

        self._write_json(HTTPStatus.OK, response_payload)

    def _is_authorized(self, api_key: str) -> bool:
        authorization = self.headers.get("Authorization", "")
        return authorization == f"Bearer {api_key}"

    def _write_json(
        self,
        status: HTTPStatus,
        payload: dict[str, object],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _write_sse_headers(self) -> None:
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _write_sse_event(self, payload: dict[str, object]) -> None:
        body = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()


def create_control_plane_server(project_root: Path, service: HostServiceConfig) -> ControlPlaneServer:
    """Create a control-plane HTTP server for the given project root."""
    normalized_service = service.normalized()
    server = ControlPlaneServer(
        (normalized_service.bind_host, normalized_service.port),
        ControlPlaneRequestHandler,
    )
    server.daemon_threads = True
    server.store = HostStateStore(project_root)
    server.service_config = normalized_service
    server.api_key = resolve_api_key(normalized_service)
    return server


def serve_control_plane(project_root: Path, service: HostServiceConfig) -> None:
    """Run the control-plane server until interrupted."""
    try:
        server = create_control_plane_server(project_root, service)
    except OSError as exc:
        raise ControlPlaneError(str(exc)) from exc

    try:
        server.serve_forever()
    finally:
        server.server_close()


def _model_payload(record: object, active_model: str | None) -> dict[str, object]:
    from aistackd.state.host import InstalledModelRecord

    installed_record = cast(InstalledModelRecord, record)
    receipt_payload = load_json_object(Path(installed_record.receipt_path))
    payload: dict[str, object] = {
        "id": installed_record.model,
        "object": "model",
        "owned_by": "aistackd",
        "active": installed_record.model == active_model,
        "source": installed_record.source,
        "backend": installed_record.backend,
        "acquisition_method": installed_record.acquisition_method,
        "artifact_path": installed_record.artifact_path,
        "size_bytes": installed_record.size_bytes,
        "sha256": installed_record.sha256,
        "status": installed_record.status,
        "installed_at": installed_record.installed_at,
    }
    for field_name in ("summary", "context_window", "quantization", "tags", "catalog_source"):
        if field_name in receipt_payload:
            payload[field_name] = receipt_payload[field_name]
    return payload
