"""Remote client runtime helper tests."""

from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import patch

from aistackd.runtime.config import RuntimeConfig
from aistackd.runtime.remote import (
    fetch_remote_runtime,
    install_remote_model,
    run_remote_smoke,
    run_remote_tool_demo,
    validate_remote_runtime,
)
from aistackd.state.profiles import Profile


class ClientRemoteTests(unittest.TestCase):
    def test_validate_remote_runtime_reports_successful_endpoints(self) -> None:
        runtime_config = _runtime_config("AISTACKD_REMOTE_API_KEY")

        with (
            patch.dict("os.environ", {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
            patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_successful_urlopen),
        ):
            result = validate_remote_runtime(runtime_config)

        self.assertTrue(result.ok)
        self.assertEqual(result.health.status_code, 200)
        self.assertEqual(result.models.status_code, 200)
        self.assertEqual(result.runtime.status_code, 200)

    def test_validate_remote_runtime_reports_auth_failure(self) -> None:
        runtime_config = _runtime_config("AISTACKD_REMOTE_API_KEY")

        with (
            patch.dict("os.environ", {"AISTACKD_REMOTE_API_KEY": "wrong-key"}, clear=False),
            patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_unauthorized_urlopen),
        ):
            result = validate_remote_runtime(runtime_config)

        self.assertFalse(result.ok)
        self.assertIn("health returned status 401", result.errors[0])

    def test_validate_remote_runtime_reports_degraded_reason(self) -> None:
        runtime_config = _runtime_config("AISTACKD_REMOTE_API_KEY")

        with (
            patch.dict("os.environ", {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
            patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_degraded_urlopen),
        ):
            result = validate_remote_runtime(runtime_config)

        self.assertFalse(result.ok)
        self.assertIn("health returned status 503: degraded (backend_process_exited)", result.errors)

    def test_fetch_remote_runtime_decodes_payload(self) -> None:
        runtime_config = _runtime_config("AISTACKD_REMOTE_API_KEY")

        with (
            patch.dict("os.environ", {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
            patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_successful_urlopen),
        ):
            payload = fetch_remote_runtime(runtime_config)

        self.assertEqual(payload["service"]["base_url"], "http://127.0.0.1:8000")

    def test_install_remote_model_posts_payload(self) -> None:
        runtime_config = _runtime_config("AISTACKD_REMOTE_API_KEY")

        with (
            patch.dict("os.environ", {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
            patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_install_urlopen),
        ):
            payload = install_remote_model(
                runtime_config,
                {
                    "model": "glm-remote",
                    "quant": "Q4_K_M",
                    "budget_gb": 12,
                    "activate": True,
                },
            )

        self.assertEqual(payload["action"], "installed")
        self.assertEqual(payload["model"]["source"], "llmfit")
        self.assertEqual(payload["active_model"], "glm-remote")

    def test_run_remote_smoke_posts_prompt_to_responses(self) -> None:
        runtime_config = _runtime_config("AISTACKD_REMOTE_API_KEY")

        with (
            patch.dict("os.environ", {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
            patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_smoke_urlopen),
        ):
            payload = run_remote_smoke(runtime_config, "say hello")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["output_text"], "Hello from llama-server")
        self.assertEqual(payload["profile"], "remote")

    def test_run_remote_tool_demo_executes_local_tool_and_posts_follow_up(self) -> None:
        runtime_config = _runtime_config("AISTACKD_REMOTE_API_KEY")
        captured_requests: list[dict[str, object]] = []

        def fake_urlopen(request_obj: object, timeout: float = 30) -> _FakeResponse:
            payload = json.loads(getattr(request_obj, "data").decode("utf-8"))
            captured_requests.append(payload)
            if len(captured_requests) == 1:
                return _FakeResponse(
                    200,
                    {
                        "id": "resp_tool",
                        "model": "remote-model",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "call_123",
                                "name": "get_local_time",
                                "arguments": "{}",
                            }
                        ],
                        "output_text": "",
                    },
                )
            return _FakeResponse(
                200,
                {
                    "id": "resp_final",
                    "model": "remote-model",
                    "output": [
                        {
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "The time is available.", "annotations": []}],
                        }
                    ],
                    "output_text": "The time is available.",
                },
            )

        with (
            patch.dict("os.environ", {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
            patch("aistackd.runtime.remote.request.urlopen", side_effect=fake_urlopen),
        ):
            payload = run_remote_tool_demo(runtime_config)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["final_output_text"], "The time is available.")
        self.assertEqual(payload["tool_calls"][0]["name"], "get_local_time")
        self.assertEqual(captured_requests[0]["tools"][0]["name"], "get_local_time")
        self.assertEqual(captured_requests[1]["previous_response_id"], "resp_tool")
        self.assertEqual(captured_requests[1]["input"][0]["type"], "function_call_output")
        self.assertIn("utc_iso8601", captured_requests[1]["input"][0]["output"])


def _runtime_config(api_key_env: str) -> RuntimeConfig:
    profile = Profile(
        name="remote",
        base_url="http://127.0.0.1:8000",
        api_key_env=api_key_env,
        model="remote-model",
        role_hint="client",
    )
    return RuntimeConfig.for_client(profile, ("codex",))


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, object]) -> None:
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

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


def _fake_successful_urlopen(request_obj: object, timeout: float = 5) -> _FakeResponse:
    url = getattr(request_obj, "full_url")
    if url.endswith("/health"):
        return _FakeResponse(200, {"status": "ok", "active_model": "remote-model"})
    if url.endswith("/v1/models"):
        return _FakeResponse(200, {"object": "list", "active_model": "remote-model", "data": []})
    if url.endswith("/admin/runtime"):
        return _FakeResponse(
            200,
            {
                "runtime": {"active_model": "remote-model", "backend_status": "configured", "installed_models": []},
                "service": {"base_url": "http://127.0.0.1:8000"},
            },
        )
    raise AssertionError(f"unexpected URL: {url}")


def _fake_unauthorized_urlopen(request_obj: object, timeout: float = 5) -> _FakeResponse:
    body = json.dumps({"error": {"message": "missing or invalid API key"}}).encode("utf-8")
    raise urllib.error.HTTPError(
        getattr(request_obj, "full_url"),
        401,
        "Unauthorized",
        hdrs=None,
        fp=_FakeErrorStream(body),
    )


def _fake_install_urlopen(request_obj: object, timeout: float = 30) -> _FakeResponse:
    body = getattr(request_obj, "data")
    decoded = json.loads(body.decode("utf-8"))
    if decoded["quant"] != "Q4_K_M" or decoded["budget_gb"] != 12:
        raise AssertionError(f"unexpected install payload: {decoded}")
    return _FakeResponse(
        200,
        {
            "action": "installed",
            "model": {
                "model": decoded["model"],
                "source": "llmfit",
                "acquisition_method": "llmfit_download",
                "artifact_path": "/managed/models/glm-remote.gguf",
            },
            "active_model": decoded["model"],
        },
    )


def _fake_degraded_urlopen(request_obj: object, timeout: float = 5) -> _FakeResponse:
    url = getattr(request_obj, "full_url")
    if url.endswith("/health"):
        return _FakeResponse(503, {"status": "degraded", "status_reason": "backend_process_exited"})
    if url.endswith("/v1/models"):
        return _FakeResponse(200, {"object": "list", "active_model": "remote-model", "data": []})
    if url.endswith("/admin/runtime"):
        return _FakeResponse(
            200,
            {
                "runtime": {"active_model": "remote-model", "backend_status": "configured", "installed_models": []},
                "service": {"base_url": "http://127.0.0.1:8000"},
                "responses_state": {"count": 1, "retention_limit": 128, "storage_dir": "/tmp/responses"},
            },
        )
    raise AssertionError(f"unexpected URL: {url}")


def _fake_smoke_urlopen(request_obj: object, timeout: float = 30) -> _FakeResponse:
    url = getattr(request_obj, "full_url")
    if not url.endswith("/v1/responses"):
        raise AssertionError(f"unexpected URL: {url}")
    payload = json.loads(getattr(request_obj, "data").decode("utf-8"))
    if payload["input"] != "say hello":
        raise AssertionError(f"unexpected smoke payload: {payload}")
    return _FakeResponse(
        200,
        {
            "id": "resp_smoke",
            "model": "remote-model",
            "output_text": "Hello from llama-server",
            "output": [],
        },
    )
