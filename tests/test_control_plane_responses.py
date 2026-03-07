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
    ResponsesStateCache,
    open_responses_stream,
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

    def test_proxy_responses_request_translates_function_tool_calls_and_follow_up_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)
            captured_requests: list[dict[str, object]] = []
            state_cache = ResponsesStateCache()

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
                request_payload = json.loads(request_obj.data.decode("utf-8"))
                captured_requests.append(request_payload)
                if len(captured_requests) == 1:
                    return _FakeResponse(
                        {
                            "id": "chatcmpl_tool",
                            "object": "chat.completion",
                            "created": 1741305600,
                            "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": "tool_calls",
                                    "message": {
                                        "role": "assistant",
                                        "content": None,
                                        "tool_calls": [
                                            {
                                                "id": "call_123",
                                                "type": "function",
                                                "function": {
                                                    "name": "list_installed_models",
                                                    "arguments": "{}",
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 14,
                                "completion_tokens": 3,
                                "total_tokens": 17,
                            },
                        }
                    )
                return _FakeResponse(
                    {
                        "id": "chatcmpl_follow_up",
                        "object": "chat.completion",
                        "created": 1741305601,
                        "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {
                                    "role": "assistant",
                                    "content": "You have one installed model.",
                                },
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 20,
                            "completion_tokens": 6,
                            "total_tokens": 26,
                        },
                    }
                )

            with patch("aistackd.control_plane.responses.request.urlopen", side_effect=fake_urlopen):
                first_payload = proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {
                        "input": "What models are installed?",
                        "tools": [
                            {
                                "type": "function",
                                "name": "list_installed_models",
                                "description": "Return installed host models.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {},
                                    "additionalProperties": False,
                                },
                                "strict": True,
                            }
                        ],
                        "tool_choice": "auto",
                        "parallel_tool_calls": False,
                    },
                    response_state_cache=state_cache,
                )
                second_payload = proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {
                        "previous_response_id": first_payload["id"],
                        "input": [
                            {
                                "type": "function_call_output",
                                "call_id": "call_123",
                                "output": {"models": ["qwen2.5-coder-7b-instruct-q4-k-m"]},
                            }
                        ],
                    },
                    response_state_cache=state_cache,
                )

            self.assertEqual(first_payload["output"][0]["type"], "function_call")
            self.assertEqual(first_payload["output"][0]["call_id"], "call_123")
            self.assertEqual(first_payload["output"][0]["name"], "list_installed_models")
            self.assertEqual(first_payload["output_text"], "")
            self.assertEqual(first_payload["tool_choice"], "auto")
            self.assertEqual(first_payload["tools"][0]["name"], "list_installed_models")

            first_request = captured_requests[0]
            self.assertEqual(first_request["tools"][0]["function"]["name"], "list_installed_models")
            self.assertEqual(first_request["tool_choice"], "auto")
            self.assertFalse(first_request["parallel_tool_calls"])

            second_request = captured_requests[1]
            self.assertEqual(second_request["messages"][0]["role"], "user")
            self.assertEqual(second_request["messages"][0]["content"], "What models are installed?")
            self.assertEqual(second_request["messages"][1]["role"], "assistant")
            self.assertEqual(second_request["messages"][1]["tool_calls"][0]["id"], "call_123")
            self.assertEqual(second_request["messages"][2]["role"], "tool")
            self.assertEqual(second_request["messages"][2]["tool_call_id"], "call_123")
            self.assertEqual(
                second_request["messages"][2]["content"],
                json.dumps({"models": ["qwen2.5-coder-7b-instruct-q4-k-m"]}),
            )

            self.assertEqual(second_payload["output_text"], "You have one installed model.")
            self.assertEqual(second_payload["output"][0]["type"], "message")

    def test_proxy_responses_request_loads_previous_response_id_from_persisted_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)
            first_cache = ResponsesStateCache(store)
            second_cache = ResponsesStateCache(store)
            captured_requests: list[dict[str, object]] = []

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
                request_payload = json.loads(request_obj.data.decode("utf-8"))
                captured_requests.append(request_payload)
                if len(captured_requests) == 1:
                    return _FakeResponse(
                        {
                            "id": "chatcmpl_tool",
                            "object": "chat.completion",
                            "created": 1741305600,
                            "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": "tool_calls",
                                    "message": {
                                        "role": "assistant",
                                        "content": None,
                                        "tool_calls": [
                                            {
                                                "id": "call_123",
                                                "type": "function",
                                                "function": {
                                                    "name": "list_installed_models",
                                                    "arguments": "{}",
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                            "usage": {"prompt_tokens": 14, "completion_tokens": 3, "total_tokens": 17},
                        }
                    )
                return _FakeResponse(
                    {
                        "id": "chatcmpl_follow_up",
                        "object": "chat.completion",
                        "created": 1741305601,
                        "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": "Recovered after restart."},
                            }
                        ],
                        "usage": {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
                    }
                )

            with patch("aistackd.control_plane.responses.request.urlopen", side_effect=fake_urlopen):
                first_payload = proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {
                        "input": "What models are installed?",
                        "tools": [
                            {
                                "type": "function",
                                "name": "list_installed_models",
                                "parameters": {
                                    "type": "object",
                                    "properties": {},
                                    "additionalProperties": False,
                                },
                            }
                        ],
                    },
                    response_state_cache=first_cache,
                )
                second_payload = proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {
                        "previous_response_id": first_payload["id"],
                        "input": [
                            {
                                "type": "function_call_output",
                                "call_id": "call_123",
                                "output": {"models": ["qwen2.5-coder-7b-instruct-q4-k-m"]},
                            }
                        ],
                    },
                    response_state_cache=second_cache,
                )

            self.assertEqual(second_payload["output_text"], "Recovered after restart.")
            self.assertEqual(captured_requests[1]["messages"][1]["tool_calls"][0]["id"], "call_123")

    def test_proxy_responses_request_reports_unknown_previous_response_id_with_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)

            with self.assertRaises(ResponsesProxyError) as excinfo:
                proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {
                        "previous_response_id": "resp_missing",
                        "input": [
                            {
                                "type": "function_call_output",
                                "call_id": "call_123",
                                "output": {"ok": True},
                            }
                        ],
                    },
                    response_state_cache=ResponsesStateCache(store),
                )

            self.assertEqual(excinfo.exception.status.value, 400)
            self.assertIn("may have expired, been pruned, or come from a different host instance", excinfo.exception.message)

    def test_open_responses_stream_translates_backend_sse_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)
            captured_request: dict[str, object] = {}
            captured_response: dict[str, object] = {}

            class _FakeStreamingResponse:
                def __init__(self, lines: list[bytes]) -> None:
                    self._lines = lines
                    self.closed = False

                def __iter__(self) -> object:
                    return iter(self._lines)

                def close(self) -> None:
                    self.closed = True

            def fake_urlopen(request_obj: object, timeout: float = 30) -> _FakeStreamingResponse:
                from urllib.request import Request

                assert isinstance(request_obj, Request)
                captured_request["url"] = request_obj.full_url
                captured_request["payload"] = json.loads(request_obj.data.decode("utf-8"))
                response = _FakeStreamingResponse(
                    [
                        b'data: {"id":"chatcmpl_fake","object":"chat.completion.chunk","created":1741305600,"model":"qwen2.5-coder-7b-instruct-q4-k-m","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}\n',
                        b"\n",
                        b'data: {"id":"chatcmpl_fake","object":"chat.completion.chunk","created":1741305601,"model":"qwen2.5-coder-7b-instruct-q4-k-m","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n',
                        b"\n",
                        b'data: {"id":"chatcmpl_fake","object":"chat.completion.chunk","created":1741305601,"model":"qwen2.5-coder-7b-instruct-q4-k-m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n',
                        b"\n",
                        b"data: [DONE]\n",
                        b"\n",
                    ]
                )
                captured_response["value"] = response
                return response

            with patch("aistackd.control_plane.responses.request.urlopen", side_effect=fake_urlopen):
                session = open_responses_stream(
                    store,
                    HostServiceConfig(),
                    {
                        "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                        "instructions": "be concise",
                        "input": "say hello",
                        "stream": True,
                    },
                )
                events = list(session.iter_events())

            self.assertEqual(captured_request["url"], "http://127.0.0.1:8011/v1/chat/completions")
            backend_payload = captured_request["payload"]
            self.assertEqual(backend_payload["model"], "qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertEqual(backend_payload["messages"][0]["role"], "system")
            self.assertEqual(backend_payload["messages"][0]["content"], "be concise")
            self.assertEqual(backend_payload["messages"][1]["role"], "user")
            self.assertEqual(backend_payload["messages"][1]["content"], "say hello")
            self.assertTrue(backend_payload["stream"])

            self.assertEqual([event["type"] for event in events], [
                "response.created",
                "response.output_text.delta",
                "response.output_text.delta",
                "response.output_text.done",
                "response.completed",
            ])
            self.assertEqual(events[1]["delta"], "Hello")
            self.assertEqual(events[2]["delta"], " world")
            self.assertEqual(events[3]["text"], "Hello world")
            self.assertEqual(events[4]["response"]["status"], "completed")
            self.assertEqual(events[4]["response"]["output_text"], "Hello world")
            self.assertEqual(events[4]["response"]["usage"]["input_tokens"], 10)
            self.assertEqual(events[4]["response"]["usage"]["output_tokens"], 2)
            self.assertEqual(events[4]["response"]["usage"]["total_tokens"], 12)
            self.assertTrue(captured_response["value"].closed)

    def test_open_responses_stream_translates_function_tool_events_and_persists_follow_up_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)
            captured_requests: list[dict[str, object]] = []
            captured_responses: list[object] = []
            state_cache = ResponsesStateCache()

            class _FakeStreamingResponse:
                def __init__(self, lines: list[bytes]) -> None:
                    self._lines = lines
                    self.closed = False

                def __iter__(self) -> object:
                    return iter(self._lines)

                def close(self) -> None:
                    self.closed = True

            class _FakeResponse:
                def __init__(self, payload: dict[str, object]) -> None:
                    self._payload = payload

                def read(self) -> bytes:
                    return json.dumps(self._payload).encode("utf-8")

                def __enter__(self) -> "_FakeResponse":
                    return self

                def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                    return False

            def fake_urlopen(request_obj: object, timeout: float = 30) -> object:
                from urllib.request import Request

                assert isinstance(request_obj, Request)
                request_payload = json.loads(request_obj.data.decode("utf-8"))
                captured_requests.append(request_payload)
                if len(captured_requests) == 1:
                    response = _FakeStreamingResponse(
                        [
                            b'data: {"id":"chatcmpl_tool","object":"chat.completion.chunk","created":1741305600,"model":"qwen2.5-coder-7b-instruct-q4-k-m","choices":[{"index":0,"delta":{"role":"assistant","tool_calls":[{"index":0,"id":"call_123","type":"function","function":{"name":"list_installed_models","arguments":"{"}}]},"finish_reason":null}]}\n',
                            b"\n",
                            b'data: {"id":"chatcmpl_tool","object":"chat.completion.chunk","created":1741305601,"model":"qwen2.5-coder-7b-instruct-q4-k-m","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":14,"completion_tokens":3,"total_tokens":17}}\n',
                            b"\n",
                            b"data: [DONE]\n",
                            b"\n",
                        ]
                    )
                    captured_responses.append(response)
                    return response
                return _FakeResponse(
                    {
                        "id": "chatcmpl_follow_up",
                        "object": "chat.completion",
                        "created": 1741305602,
                        "model": "qwen2.5-coder-7b-instruct-q4-k-m",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {
                                    "role": "assistant",
                                    "content": "You have one installed model.",
                                },
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 20,
                            "completion_tokens": 6,
                            "total_tokens": 26,
                        },
                    }
                )

            with patch("aistackd.control_plane.responses.request.urlopen", side_effect=fake_urlopen):
                session = open_responses_stream(
                    store,
                    HostServiceConfig(),
                    {
                        "input": "What models are installed?",
                        "tools": [
                            {
                                "type": "function",
                                "name": "list_installed_models",
                                "parameters": {
                                    "type": "object",
                                    "properties": {},
                                    "additionalProperties": False,
                                },
                            }
                        ],
                        "tool_choice": "auto",
                        "stream": True,
                    },
                    response_state_cache=state_cache,
                )
                events = list(session.iter_events())

                completion_event = events[-1]
                follow_up = proxy_responses_request(
                    store,
                    HostServiceConfig(),
                    {
                        "previous_response_id": completion_event["response"]["id"],
                        "input": [
                            {
                                "type": "function_call_output",
                                "call_id": "call_123",
                                "output": {"models": ["qwen2.5-coder-7b-instruct-q4-k-m"]},
                            }
                        ],
                    },
                    response_state_cache=state_cache,
                )

            self.assertEqual([event["type"] for event in events], [
                "response.created",
                "response.output_item.added",
                "response.function_call_arguments.delta",
                "response.function_call_arguments.delta",
                "response.function_call_arguments.done",
                "response.output_item.done",
                "response.completed",
            ])
            self.assertEqual(events[1]["item"]["type"], "function_call")
            self.assertEqual(events[1]["item"]["call_id"], "call_123")
            self.assertEqual(events[2]["delta"], "{")
            self.assertEqual(events[3]["delta"], "}")
            self.assertEqual(events[4]["arguments"], "{}")
            self.assertEqual(events[5]["item"]["arguments"], "{}")
            self.assertEqual(events[6]["response"]["output"][0]["type"], "function_call")
            self.assertEqual(events[6]["response"]["output"][0]["arguments"], "{}")
            self.assertTrue(captured_responses[0].closed)

            first_request = captured_requests[0]
            self.assertTrue(first_request["stream"])
            self.assertEqual(first_request["tools"][0]["function"]["name"], "list_installed_models")

            second_request = captured_requests[1]
            self.assertEqual(second_request["messages"][1]["tool_calls"][0]["id"], "call_123")
            self.assertEqual(second_request["messages"][2]["role"], "tool")
            self.assertEqual(second_request["messages"][2]["tool_call_id"], "call_123")
            self.assertEqual(follow_up["output_text"], "You have one installed model.")

    def test_open_responses_stream_rejects_invalid_stream_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _create_ready_host_state(Path(tmpdir), backend_port=8011)

            with self.assertRaises(ResponsesProxyError) as excinfo:
                open_responses_stream(
                    store,
                    HostServiceConfig(),
                    {"input": "hello", "stream": "yes"},
                )

            self.assertEqual(excinfo.exception.status.value, 400)
            self.assertIn("stream must be a boolean", excinfo.exception.message)


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
