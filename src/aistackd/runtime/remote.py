"""Remote client helpers for authenticated control-plane access."""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime
from dataclasses import dataclass
from urllib import error, request

from aistackd.control_plane import (
    ADMIN_MODELS_ACTIVATE_ENDPOINT,
    ADMIN_MODELS_INSTALL_ENDPOINT,
    ADMIN_MODELS_RECOMMEND_ENDPOINT,
    ADMIN_MODELS_SEARCH_ENDPOINT,
    ADMIN_RUNTIME_ENDPOINT,
    HEALTH_ENDPOINT,
    MODELS_ENDPOINT,
    RESPONSES_ENDPOINT,
)
from aistackd.runtime.config import RuntimeConfig

DEFAULT_REMOTE_TIMEOUT_SECONDS = 5
DEFAULT_REMOTE_WRITE_TIMEOUT_SECONDS = 30
DEFAULT_REMOTE_SMOKE_PROMPT = "say hello in one short sentence"
DEFAULT_REMOTE_TOOL_DEMO_PROMPT = "Use the get_local_time tool and answer with the current UTC time."


class RemoteClientError(RuntimeError):
    """Raised when a remote control-plane request cannot complete successfully."""


@dataclass(frozen=True)
class RemoteJsonResponse:
    """One JSON response returned by the remote control plane."""

    status_code: int
    payload: dict[str, object]

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def to_dict(self) -> dict[str, object]:
        return {
            "status_code": self.status_code,
            "ok": self.ok,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ClientValidationResult:
    """Validation summary for one active client profile."""

    active_profile: str
    base_url: str
    responses_base_url: str
    health: RemoteJsonResponse | None
    models: RemoteJsonResponse | None
    runtime: RemoteJsonResponse | None
    ok: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "active_profile": self.active_profile,
            "base_url": self.base_url,
            "responses_base_url": self.responses_base_url,
            "ok": self.ok,
            "errors": list(self.errors),
        }
        if self.health is not None:
            payload["health"] = self.health.to_dict()
        if self.models is not None:
            payload["models"] = self.models.to_dict()
        if self.runtime is not None:
            payload["runtime"] = self.runtime.to_dict()
        return payload


def resolve_remote_api_key(runtime_config: RuntimeConfig) -> str:
    """Resolve the configured API key for one client runtime config."""
    api_key = os.getenv(runtime_config.api_key_env, "").strip()
    if not api_key:
        raise RemoteClientError(f"api key environment variable '{runtime_config.api_key_env}' is not set or empty")
    return api_key


def validate_remote_runtime(
    runtime_config: RuntimeConfig,
    *,
    timeout_seconds: int = DEFAULT_REMOTE_TIMEOUT_SECONDS,
) -> ClientValidationResult:
    """Validate connectivity, auth, and baseline admin/runtime endpoints."""
    api_key = resolve_remote_api_key(runtime_config)

    try:
        health = get_remote_json(
            runtime_config,
            HEALTH_ENDPOINT,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            tolerate_http_errors=True,
        )
        models = get_remote_json(
            runtime_config,
            MODELS_ENDPOINT,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            tolerate_http_errors=True,
        )
        runtime = get_remote_json(
            runtime_config,
            ADMIN_RUNTIME_ENDPOINT,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            tolerate_http_errors=True,
        )
    except RemoteClientError as exc:
        return ClientValidationResult(
            active_profile=runtime_config.active_profile,
            base_url=runtime_config.base_url,
            responses_base_url=runtime_config.responses_base_url,
            health=None,
            models=None,
            runtime=None,
            ok=False,
            errors=(str(exc),),
        )

    errors: list[str] = []
    for name, response in (("health", health), ("models", models), ("runtime", runtime)):
        if not response.ok:
            errors.append(_response_error_message(name, response))
    if health.ok:
        remote_status = health.payload.get("status")
        if remote_status != "ok":
            status_reason = health.payload.get("status_reason")
            if isinstance(status_reason, str) and status_reason:
                errors.append(f"health endpoint reported status '{remote_status}' ({status_reason})")
            else:
                errors.append(f"health endpoint reported status '{remote_status}'")

    return ClientValidationResult(
        active_profile=runtime_config.active_profile,
        base_url=runtime_config.base_url,
        responses_base_url=runtime_config.responses_base_url,
        health=health,
        models=models,
        runtime=runtime,
        ok=not errors,
        errors=tuple(errors),
    )


def fetch_remote_runtime(
    runtime_config: RuntimeConfig,
    *,
    timeout_seconds: int = DEFAULT_REMOTE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Fetch authenticated runtime state from the remote control plane."""
    response = get_remote_json(
        runtime_config,
        ADMIN_RUNTIME_ENDPOINT,
        api_key=resolve_remote_api_key(runtime_config),
        timeout_seconds=timeout_seconds,
    )
    return response.payload


def fetch_remote_models(
    runtime_config: RuntimeConfig,
    *,
    timeout_seconds: int = DEFAULT_REMOTE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Fetch installed model inventory from the remote control plane."""
    response = get_remote_json(
        runtime_config,
        MODELS_ENDPOINT,
        api_key=resolve_remote_api_key(runtime_config),
        timeout_seconds=timeout_seconds,
    )
    return response.payload


def search_remote_models(
    runtime_config: RuntimeConfig,
    query: str | None,
    *,
    timeout_seconds: int = DEFAULT_REMOTE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Search remote models through the authenticated admin API."""
    return post_remote_json(
        runtime_config,
        ADMIN_MODELS_SEARCH_ENDPOINT,
        {"query": query},
        timeout_seconds=timeout_seconds,
    )


def recommend_remote_models(
    runtime_config: RuntimeConfig,
    *,
    timeout_seconds: int = DEFAULT_REMOTE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Fetch remote model recommendations through the authenticated admin API."""
    return post_remote_json(
        runtime_config,
        ADMIN_MODELS_RECOMMEND_ENDPOINT,
        {},
        timeout_seconds=timeout_seconds,
    )


def install_remote_model(
    runtime_config: RuntimeConfig,
    payload: dict[str, object],
    *,
    timeout_seconds: int = DEFAULT_REMOTE_WRITE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Install one remote model through the authenticated admin API."""
    return post_remote_json(
        runtime_config,
        ADMIN_MODELS_INSTALL_ENDPOINT,
        payload,
        timeout_seconds=timeout_seconds,
    )


def activate_remote_model(
    runtime_config: RuntimeConfig,
    model_name: str,
    *,
    timeout_seconds: int = DEFAULT_REMOTE_WRITE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Activate one remote model through the authenticated admin API."""
    return post_remote_json(
        runtime_config,
        ADMIN_MODELS_ACTIVATE_ENDPOINT,
        {"model": model_name},
        timeout_seconds=timeout_seconds,
    )


def run_remote_smoke(
    runtime_config: RuntimeConfig,
    prompt: str = DEFAULT_REMOTE_SMOKE_PROMPT,
    *,
    timeout_seconds: int = DEFAULT_REMOTE_WRITE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run one non-streaming smoke request against the remote Responses endpoint."""
    response = post_remote_json(
        runtime_config,
        RESPONSES_ENDPOINT,
        {"input": prompt, "stream": False},
        timeout_seconds=timeout_seconds,
    )
    return {
        "profile": runtime_config.active_profile,
        "base_url": runtime_config.base_url,
        "responses_base_url": runtime_config.responses_base_url,
        "prompt": prompt,
        "model": response.get("model", runtime_config.model),
        "response_id": response.get("id"),
        "output_text": response.get("output_text"),
        "response": response,
        "ok": True,
    }


def run_remote_tool_demo(
    runtime_config: RuntimeConfig,
    prompt: str = DEFAULT_REMOTE_TOOL_DEMO_PROMPT,
    *,
    max_steps: int = 4,
    timeout_seconds: int = DEFAULT_REMOTE_WRITE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run one client-managed local tool loop against the remote Responses endpoint."""
    if max_steps <= 0:
        raise RemoteClientError("--max-steps must be a positive integer")

    tool_calls: list[dict[str, object]] = []
    previous_response_id: str | None = None
    pending_input: object = prompt

    for _ in range(max_steps):
        request_payload: dict[str, object] = {
            "input": pending_input,
            "tools": list(_tool_demo_definitions()),
            "tool_choice": "auto",
        }
        if previous_response_id is not None:
            request_payload["previous_response_id"] = previous_response_id

        response = post_remote_json(
            runtime_config,
            RESPONSES_ENDPOINT,
            request_payload,
            timeout_seconds=timeout_seconds,
        )
        previous_response_id = _require_response_string(response.get("id"), "response.id")
        output_items = response.get("output")
        if not isinstance(output_items, list):
            raise RemoteClientError("responses endpoint returned an invalid output payload")

        function_calls = [item for item in output_items if isinstance(item, dict) and item.get("type") == "function_call"]
        if not function_calls:
            return {
                "profile": runtime_config.active_profile,
                "base_url": runtime_config.base_url,
                "responses_base_url": runtime_config.responses_base_url,
                "prompt": prompt,
                "model": response.get("model", runtime_config.model),
                "steps": len(tool_calls) + 1,
                "tool_calls": tool_calls,
                "final_output_text": response.get("output_text"),
                "response": response,
                "ok": True,
            }

        follow_up_items: list[dict[str, object]] = []
        for function_call in function_calls:
            call_id = _require_response_string(function_call.get("call_id"), "function_call.call_id")
            tool_name = _require_response_string(function_call.get("name"), "function_call.name")
            arguments = _parse_tool_arguments(function_call.get("arguments"))
            output = _execute_local_demo_tool(runtime_config, tool_name, arguments)
            tool_calls.append(
                {
                    "call_id": call_id,
                    "name": tool_name,
                    "arguments": arguments,
                    "output": output,
                }
            )
            follow_up_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                }
            )
        pending_input = follow_up_items

    raise RemoteClientError(f"tool-call demo exceeded max steps ({max_steps}) without a final assistant message")


def get_remote_json(
    runtime_config: RuntimeConfig,
    path: str,
    *,
    api_key: str,
    timeout_seconds: int,
    tolerate_http_errors: bool = False,
) -> RemoteJsonResponse:
    """Issue one authenticated GET request to the configured control plane."""
    request_object = request.Request(
        f"{runtime_config.base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    return perform_json_request(
        request_object,
        timeout_seconds=timeout_seconds,
        tolerate_http_errors=tolerate_http_errors,
    )


def post_remote_json(
    runtime_config: RuntimeConfig,
    path: str,
    payload: dict[str, object],
    *,
    timeout_seconds: int,
) -> dict[str, object]:
    """Issue one authenticated POST request to the configured control plane."""
    request_object = request.Request(
        f"{runtime_config.base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resolve_remote_api_key(runtime_config)}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response = perform_json_request(request_object, timeout_seconds=timeout_seconds)
    return response.payload


def perform_json_request(
    request_object: request.Request,
    *,
    timeout_seconds: int,
    tolerate_http_errors: bool = False,
) -> RemoteJsonResponse:
    """Perform one JSON request against a remote control-plane endpoint."""
    try:
        with request.urlopen(request_object, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            return RemoteJsonResponse(status_code=response.status, payload=_decode_json_object(body))
    except error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        finally:
            exc.close()
        response = RemoteJsonResponse(status_code=exc.code, payload=_decode_json_object(body))
        if tolerate_http_errors:
            return response
        raise RemoteClientError(_response_error_message(request_object.full_url, response)) from exc
    except error.URLError as exc:
        raise RemoteClientError(f"failed to reach {request_object.full_url}: {exc.reason}") from exc
    except OSError as exc:
        raise RemoteClientError(f"request failed for {request_object.full_url}: {exc}") from exc


def _decode_json_object(body: str) -> dict[str, object]:
    try:
        decoded = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return {"raw_body": body}
    if isinstance(decoded, dict):
        return decoded
    return {"payload": decoded}


def _response_error_message(label: str, response: RemoteJsonResponse) -> str:
    payload = response.payload
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message.strip():
            return f"{label} returned status {response.status_code}: {message.strip()}"
    status_value = payload.get("status")
    status_reason = payload.get("status_reason")
    if isinstance(status_value, str) and status_value.strip():
        if isinstance(status_reason, str) and status_reason.strip():
            return (
                f"{label} returned status {response.status_code}: "
                f"{status_value.strip()} ({status_reason.strip()})"
            )
        return f"{label} returned status {response.status_code}: {status_value.strip()}"
    return f"{label} returned status {response.status_code}"


def _tool_demo_definitions() -> tuple[dict[str, object], ...]:
    return (
        {
            "type": "function",
            "name": "get_local_time",
            "description": "Return the frontend machine's current local and UTC timestamps.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_frontend_context",
            "description": "Return the frontend hostname and active profile name.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    )


def _execute_local_demo_tool(
    runtime_config: RuntimeConfig,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    if arguments:
        unexpected = ", ".join(sorted(arguments))
        raise RemoteClientError(f"local tool '{tool_name}' does not accept arguments: {unexpected}")
    if tool_name == "get_local_time":
        now_local = datetime.now().astimezone()
        now_utc = now_local.astimezone(UTC)
        return {
            "local_iso8601": now_local.isoformat(),
            "utc_iso8601": now_utc.isoformat(),
            "unix_timestamp": int(now_utc.timestamp()),
        }
    if tool_name == "get_frontend_context":
        return {
            "hostname": socket.gethostname(),
            "profile": runtime_config.active_profile,
            "base_url": runtime_config.base_url,
        }
    raise RemoteClientError(f"local tool '{tool_name}' is not implemented in this demo")


def _parse_tool_arguments(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            decoded = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError as exc:
            raise RemoteClientError(f"tool call arguments were not valid JSON: {exc}") from exc
    else:
        decoded = value
    if not isinstance(decoded, dict):
        raise RemoteClientError("tool call arguments must decode to a JSON object")
    return decoded


def _require_response_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RemoteClientError(f"missing or invalid {field_name}")
    return value
