"""Socket-free control-plane responses proxy tests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.control_plane.responses import (
    ResponsesProxyError,
    parse_json_request_body,
    proxy_responses_request,
)
from aistackd.models.sources import local_source_model
from aistackd.runtime.backends import adopt_backend_installation, discover_llama_cpp_installation
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostBackendProcess, HostStateStore


class ControlPlaneResponsesTests(unittest.TestCase):
    def test_parse_json_request_body_rejects_invalid_json(self) -> None:
        with self.assertRaises(ResponsesProxyError) as excinfo:
            parse_json_request_body(b"{invalid")

        self.assertEqual(excinfo.exception.status.value, 400)
        self.assertIn("invalid JSON request body", excinfo.exception.message)

    def test_proxy_responses_request_translates_to_backend_chat_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)
            captured_request: dict[str, object] = {}

            class _FakeResponse:
                def __init__(self, payload: dict[str, object]) -> None:
                    self._payload = payload

                def read(self) -> bytes:
                    return json.dumps(self._payload).encode("utf-8")

                def __enter__(self) -> "_FakeResponse":
                    return self

                def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                    return False

            def fake_urlopen(request_obj: object, timeout: float = 30) -> _FakeResponse:
                from urllib.request import Request

                assert isinstance(request_obj, Request)
                captured_request["url"] = request_obj.full_url
                captured_request["payload"] = json.loads(request_obj.data.decode("utf-8"))
                return _FakeResponse(
                    {
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
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 15,
                        },
                    }
                )

            with patch("aistackd.control_plane.responses.request.urlopen", side_effect=fake_urlopen):
                payload = proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {
                        "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                        "instructions": "be concise",
                        "input": [
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": "say hello"}],
                            }
                        ],
                        "max_output_tokens": 64,
                        "temperature": 0.1,
                    },
                )

            self.assertEqual(payload["object"], "response")
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["model"], "qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertEqual(payload["output_text"], "Hello from llama-server")
            self.assertEqual(payload["usage"]["input_tokens"], 10)
            self.assertEqual(payload["usage"]["output_tokens"], 5)
            self.assertEqual(payload["usage"]["total_tokens"], 15)

            self.assertEqual(captured_request["url"], "http://127.0.0.1:8011/v1/chat/completions")
            backend_payload = captured_request["payload"]
            self.assertEqual(backend_payload["model"], "qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertEqual(backend_payload["messages"][0]["role"], "system")
            self.assertEqual(backend_payload["messages"][0]["content"], "be concise")
            self.assertEqual(backend_payload["messages"][1]["role"], "user")
            self.assertEqual(backend_payload["messages"][1]["content"], "say hello")
            self.assertEqual(backend_payload["max_tokens"], 64)
            self.assertEqual(backend_payload["temperature"], 0.1)
            self.assertFalse(backend_payload["stream"])

    def test_proxy_responses_request_rejects_streaming(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)

            with self.assertRaises(ResponsesProxyError) as excinfo:
                proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {"input": "hello", "stream": True},
                )

            self.assertEqual(excinfo.exception.status.value, 400)
            self.assertIn("streaming responses are not implemented yet", excinfo.exception.message)


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
