"""Control-plane endpoint tests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from aistackd.control_plane import create_control_plane_server
from aistackd.models.sources import local_source_model
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostBackendProcess, HostStateStore


class ControlPlaneTests(unittest.TestCase):
    def test_control_plane_serves_health_and_models_with_bearer_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m", source="llmfit")
            artifact_path = _create_fake_gguf(Path(tmpdir), "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
            record, _ = store.install_model(
                source_model,
                acquisition_source="local",
                acquisition_method="explicit_local_gguf",
                artifact_path=artifact_path,
                size_bytes=artifact_path.stat().st_size,
                sha256=_sha256(artifact_path),
            )
            store.activate_model(record.model)
            backend_root = _create_fake_backend_root(Path(tmpdir))
            store.save_backend_installation(
                adopt_backend_installation(discover_llama_cpp_installation(backend_root=backend_root))
            )
            backend_log_path = store.paths.backend_log_path()
            backend_log_path.parent.mkdir(parents=True, exist_ok=True)
            backend_log_path.write_text("", encoding="utf-8")
            store.save_backend_process(
                HostBackendProcess(
                    backend="llama.cpp",
                    status="running",
                    pid=os.getpid(),
                    command=(
                        str((backend_root / "bin" / "llama-server").resolve()),
                        "--model",
                        record.artifact_path,
                    ),
                    bind_host="127.0.0.1",
                    port=8011,
                    model=record.model,
                    artifact_path=record.artifact_path,
                    server_binary=str((backend_root / "bin" / "llama-server").resolve()),
                    log_path=str(backend_log_path),
                    started_at="2026-03-07T00:00:00+00:00",
                )
            )

            with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                server = create_control_plane_server(
                    Path(tmpdir),
                    HostServiceConfig(bind_host="127.0.0.1", port=0, api_key_env="AISTACKD_API_KEY"),
                )

            try:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                time.sleep(0.02)
                port = server.server_address[1]

                health_payload = _request_json(
                    f"http://127.0.0.1:{port}/health",
                    token="test-key",
                )
                self.assertEqual(health_payload["status"], "ok")
                self.assertEqual(health_payload["backend_status"], "configured")
                self.assertEqual(health_payload["backend_process_status"], "running")
                self.assertEqual(health_payload["active_model"], record.model)
                self.assertEqual(health_payload["installed_model_count"], 1)
                self.assertEqual(health_payload["backend_base_url"], "http://127.0.0.1:8011")
                self.assertTrue(str(health_payload["server_binary"]).endswith("llama-server"))

                models_payload = _request_json(
                    f"http://127.0.0.1:{port}/v1/models",
                    token="test-key",
                )
                self.assertEqual(models_payload["object"], "list")
                self.assertEqual(models_payload["active_model"], record.model)
                self.assertEqual(models_payload["data"][0]["id"], record.model)
                self.assertTrue(models_payload["data"][0]["active"])
                self.assertEqual(models_payload["data"][0]["source"], "local")
                self.assertEqual(models_payload["data"][0]["acquisition_method"], "explicit_local_gguf")
                self.assertEqual(models_payload["data"][0]["catalog_source"], "llmfit")

                with self.assertRaises(urllib.error.HTTPError) as excinfo:
                    _request_json(f"http://127.0.0.1:{port}/health")
                self.assertEqual(excinfo.exception.code, 401)
                excinfo.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)

    def test_control_plane_proxies_responses_requests_to_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_server = _create_fake_backend_server()
            backend_thread = threading.Thread(target=backend_server.serve_forever, daemon=True)
            backend_thread.start()

            try:
                backend_port = backend_server.server_address[1]
                store = _create_ready_host_state(Path(tmpdir), backend_port=backend_port)

                with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                    server = create_control_plane_server(
                        Path(tmpdir),
                        HostServiceConfig(
                            bind_host="127.0.0.1",
                            port=0,
                            api_key_env="AISTACKD_API_KEY",
                            backend_bind_host="127.0.0.1",
                            backend_port=backend_port,
                        ),
                    )

                try:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    time.sleep(0.02)
                    port = server.server_address[1]

                    responses_payload = _request_json(
                        f"http://127.0.0.1:{port}/v1/responses",
                        token="test-key",
                        method="POST",
                        payload={
                            "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                            "instructions": "be concise",
                            "input": [
                                {
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "say hello"}],
                                }
                            ],
                            "max_output_tokens": 128,
                            "temperature": 0.2,
                        },
                    )

                    self.assertEqual(responses_payload["object"], "response")
                    self.assertEqual(responses_payload["status"], "completed")
                    self.assertEqual(responses_payload["model"], "qwen2.5-coder-7b-instruct-q4-k-m")
                    self.assertEqual(responses_payload["output_text"], "Hello from llama-server")
                    self.assertEqual(
                        responses_payload["output"][0]["content"][0]["text"],
                        "Hello from llama-server",
                    )
                    self.assertEqual(responses_payload["usage"]["input_tokens"], 12)
                    self.assertEqual(responses_payload["usage"]["output_tokens"], 4)
                    self.assertEqual(responses_payload["usage"]["total_tokens"], 16)

                    backend_request = backend_server.last_request_payload
                    self.assertIsNotNone(backend_request)
                    self.assertEqual(backend_request["model"], "qwen2.5-coder-7b-instruct-q4-k-m")
                    self.assertEqual(backend_request["messages"][0]["role"], "system")
                    self.assertEqual(backend_request["messages"][0]["content"], "be concise")
                    self.assertEqual(backend_request["messages"][1]["role"], "user")
                    self.assertEqual(backend_request["messages"][1]["content"], "say hello")
                    self.assertEqual(backend_request["max_tokens"], 128)
                    self.assertEqual(backend_request["temperature"], 0.2)
                    self.assertFalse(backend_request["stream"])

                    with self.assertRaises(urllib.error.HTTPError) as excinfo:
                        _request_json(
                            f"http://127.0.0.1:{port}/v1/responses",
                            token="test-key",
                            method="POST",
                            payload={"input": "hello", "stream": True},
                        )
                    self.assertEqual(excinfo.exception.code, 400)
                    error_payload = json.loads(excinfo.exception.read().decode("utf-8"))
                    self.assertIn("streaming responses are not implemented yet", error_payload["error"]["message"])
                    excinfo.exception.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)
            finally:
                backend_server.shutdown()
                backend_server.server_close()
                backend_thread.join(timeout=1)


def _request_json(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, method=method, data=body)
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


class _FakeBackendServer(ThreadingHTTPServer):
    response_payload: dict[str, object]
    last_request_payload: dict[str, object] | None


class _FakeBackendRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        payload = json.loads(body.decode("utf-8"))
        backend_server = self.server
        assert isinstance(backend_server, _FakeBackendServer)
        backend_server.last_request_payload = payload

        response_body = json.dumps(backend_server.response_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _create_fake_backend_server() -> _FakeBackendServer:
    server = _FakeBackendServer(("127.0.0.1", 0), _FakeBackendRequestHandler)
    server.daemon_threads = True
    server.last_request_payload = None
    server.response_payload = {
        "id": "chatcmpl_fake",
        "object": "chat.completion",
        "created": 1741305600,
        "model": "qwen2.5-coder-7b-instruct-q4-k-m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Hello from llama-server",
                },
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 4,
            "total_tokens": 16,
        },
    }
    return server


def _create_ready_host_state(project_root: Path, *, backend_port: int) -> HostStateStore:
    store = HostStateStore(project_root)
    source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m", source="llmfit")
    artifact_path = _create_fake_gguf(project_root, "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
    record, _ = store.install_model(
        source_model,
        acquisition_source="local",
        acquisition_method="explicit_local_gguf",
        artifact_path=artifact_path,
        size_bytes=artifact_path.stat().st_size,
        sha256=_sha256(artifact_path),
    )
    store.activate_model(record.model)
    backend_root = _create_fake_backend_root(project_root)
    store.save_backend_installation(
        adopt_backend_installation(discover_llama_cpp_installation(backend_root=backend_root))
    )
    backend_log_path = store.paths.backend_log_path()
    backend_log_path.parent.mkdir(parents=True, exist_ok=True)
    backend_log_path.write_text("", encoding="utf-8")
    store.save_backend_process(
        HostBackendProcess(
            backend="llama.cpp",
            status="running",
            pid=os.getpid(),
            command=(
                str((backend_root / "bin" / "llama-server").resolve()),
                "--model",
                record.artifact_path,
            ),
            bind_host="127.0.0.1",
            port=backend_port,
            model=record.model,
            artifact_path=record.artifact_path,
            server_binary=str((backend_root / "bin" / "llama-server").resolve()),
            log_path=str(backend_log_path),
            started_at="2026-03-07T00:00:00+00:00",
        )
    )
    return store


def _create_fake_backend_root(root: Path) -> Path:
    backend_root = root / "llama.cpp"
    bin_dir = backend_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for binary_name in ("llama-server", "llama-cli"):
        path = bin_dir / binary_name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return backend_root


def _create_fake_gguf(root: Path, filename: str) -> Path:
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_root / filename
    artifact_path.write_bytes(b"GGUF\x00test-model\n")
    return artifact_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
