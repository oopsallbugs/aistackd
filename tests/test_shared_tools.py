"""Tests for repo-owned baseline tool templates."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


TOOLS_ROOT = Path(__file__).resolve().parents[1] / "tools"


class SharedToolsTests(unittest.TestCase):
    def test_responses_smoke_non_stream_succeeds(self) -> None:
        module = load_tool_module("responses-smoke.py", "responses_smoke_tool")

        with (
            patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False),
            patch.object(module.request, "urlopen", side_effect=_fake_responses_smoke_urlopen),
        ):
            exit_code, stdout, stderr = invoke_tool(
                module,
                ["hello", "--base-url", "http://127.0.0.1:8000", "--api-key-env", "AISTACKD_API_KEY", "--format", "json"],
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["output_text"], "Hello from llama-server")

    def test_responses_smoke_stream_succeeds(self) -> None:
        module = load_tool_module("responses-smoke.py", "responses_smoke_stream_tool")

        with (
            patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False),
            patch.object(module.request, "urlopen", side_effect=_fake_responses_stream_urlopen),
        ):
            exit_code, stdout, stderr = invoke_tool(
                module,
                [
                    "hello",
                    "--stream",
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--format",
                    "json",
                ],
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["event_types"][-1], "response.completed")
        self.assertEqual(payload["output_text"], "Hello from llama-server")

    def test_runtime_wait_retries_until_ready(self) -> None:
        module = load_tool_module("runtime-wait.py", "runtime_wait_tool")
        attempts = {"count": 0}

        def fake_urlopen(request_obj: object, timeout: float = 5) -> object:
            attempts["count"] += 1
            if attempts["count"] == 1:
                body = json.dumps({"status": "degraded", "backend_process_status": "starting"}).encode("utf-8")
                raise urllib.error.HTTPError(
                    getattr(request_obj, "full_url"),
                    503,
                    "Service Unavailable",
                    hdrs=None,
                    fp=_FakeErrorStream(body),
                )
            return _FakeResponse(
                200,
                {
                    "status": "ok",
                    "active_model": "local-model",
                    "backend_process_status": "running",
                },
            )

        with (
            patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False),
            patch.object(module.request, "urlopen", side_effect=fake_urlopen),
            patch.object(module.time, "sleep", return_value=None),
        ):
            exit_code, stdout, stderr = invoke_tool(
                module,
                [
                    "ready",
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--format",
                    "json",
                    "--timeout",
                    "5",
                    "--interval",
                    "0.1",
                ],
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["attempts"], 2)

    def test_model_admin_install_forwards_quant_and_budget(self) -> None:
        module = load_tool_module("model-admin.py", "model_admin_tool")

        def fake_urlopen(request_obj: object, timeout: float = 30) -> object:
            payload = json.loads(getattr(request_obj, "data").decode("utf-8"))
            self.assertEqual(payload["quant"], "Q4_K_M")
            self.assertEqual(payload["budget_gb"], 16.0)
            return _FakeResponse(
                200,
                {
                    "action": "installed",
                    "model": {
                        "model": payload["model"],
                        "source": "llmfit",
                        "acquisition_method": "llmfit_download",
                        "artifact_path": "/managed/models/qwen.gguf",
                    },
                    "active_model": payload["model"],
                },
            )

        with (
            patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False),
            patch.object(module.request, "urlopen", side_effect=fake_urlopen),
        ):
            exit_code, stdout, stderr = invoke_tool(
                module,
                [
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "install",
                    "qwen2.5-coder-7b-instruct-q4-k-m",
                    "--quant",
                    "Q4_K_M",
                    "--budget",
                    "16",
                    "--format",
                    "json",
                ],
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["model"]["acquisition_method"], "llmfit_download")


def load_tool_module(filename: str, module_name: str) -> ModuleType:
    tool_path = TOOLS_ROOT / filename
    spec = importlib.util.spec_from_file_location(module_name, tool_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load tool module from {tool_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke_tool(module: ModuleType, argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main(argv)
    return int(exit_code), stdout.getvalue(), stderr.getvalue()


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, object], *, lines: list[bytes] | None = None) -> None:
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")
        self._lines = lines or []

    def read(self) -> bytes:
        return self._payload

    def __iter__(self) -> object:
        return iter(self._lines)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeErrorStream:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, *_args: object, **_kwargs: object) -> bytes:
        payload = self._payload
        self._payload = b""
        return payload

    def close(self) -> None:
        return None


def _fake_responses_smoke_urlopen(request_obj: object, timeout: float = 15) -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "object": "response",
            "status": "completed",
            "output_text": "Hello from llama-server",
        },
    )


def _fake_responses_stream_urlopen(request_obj: object, timeout: float = 15) -> _FakeResponse:
    return _FakeResponse(
        200,
        {},
        lines=[
            b'data: {"type":"response.created","response":{"status":"in_progress"}}\n',
            b"\n",
            b'data: {"type":"response.output_text.delta","delta":"Hello"}\n',
            b"\n",
            b'data: {"type":"response.output_text.delta","delta":" from llama-server"}\n',
            b"\n",
            b'data: {"type":"response.output_text.done","text":"Hello from llama-server"}\n',
            b"\n",
            b'data: {"type":"response.completed","response":{"status":"completed","output_text":"Hello from llama-server"}}\n',
            b"\n",
        ],
    )
