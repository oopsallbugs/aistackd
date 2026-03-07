"""Open Responses translation and backend proxy helpers."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib import error, request
from uuid import uuid4

from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostRuntimeState, HostStateStore

CHAT_COMPLETIONS_ENDPOINT = "/v1/chat/completions"


@dataclass(frozen=True)
class ResponsesProxyError(RuntimeError):
    """Typed control-plane error for request validation and backend proxy failures."""

    status: HTTPStatus
    message: str
    error_type: str = "invalid_request_error"

    def to_payload(self) -> dict[str, object]:
        """Return the error payload shape used by the control plane."""
        return {"error": {"message": self.message, "type": self.error_type}}


def proxy_responses_request(
    store: HostStateStore,
    service: HostServiceConfig,
    payload: dict[str, object],
) -> dict[str, object]:
    """Proxy one Open Responses request to the running llama-server backend."""
    runtime = store.load_runtime_state()
    model_name = _resolve_requested_model(runtime, payload)
    backend_payload = _build_backend_chat_payload(payload, model_name=model_name)
    backend_response = _invoke_backend_chat_completion(runtime, service, backend_payload)
    return _build_open_responses_payload(payload, model_name=model_name, backend_response=backend_response)


def parse_json_request_body(body: bytes) -> dict[str, object]:
    """Decode one JSON request body into an object payload."""
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"invalid JSON request body: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "request body must be a JSON object")
    return decoded


def _resolve_requested_model(runtime: HostRuntimeState, payload: dict[str, object]) -> str:
    active_model = runtime.active_model
    if active_model is None:
        raise ResponsesProxyError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "no active model is configured for host runtime",
            error_type="server_error",
        )
    if runtime.activation_state != "ready":
        raise ResponsesProxyError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            f"active model '{active_model}' is not ready for serving (activation_state={runtime.activation_state})",
            error_type="server_error",
        )
    if runtime.backend_process_status != "running" or runtime.backend_process is None:
        raise ResponsesProxyError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "backend process is not running for host inference",
            error_type="server_error",
        )

    requested_model = payload.get("model")
    if requested_model is None:
        return active_model
    if not isinstance(requested_model, str) or not requested_model.strip():
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "model must be a non-empty string when provided")
    normalized_model = requested_model.strip()
    if normalized_model != active_model:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            f"requested model '{normalized_model}' does not match active model '{active_model}'",
        )
    return normalized_model


def _build_backend_chat_payload(
    payload: dict[str, object],
    *,
    model_name: str,
) -> dict[str, object]:
    stream = payload.get("stream")
    if stream not in (None, False):
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "streaming responses are not implemented yet; resend the request with stream=false or omitted",
        )

    messages = _build_chat_messages(payload)
    if not messages:
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "input or instructions must produce at least one text message")

    backend_payload: dict[str, object] = {
        "model": model_name,
        "messages": messages,
        "stream": False,
    }

    for field_name in ("temperature", "top_p"):
        value = payload.get(field_name)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"{field_name} must be numeric when provided")
        backend_payload[field_name] = value

    max_output_tokens = payload.get("max_output_tokens")
    if max_output_tokens is not None:
        if not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "max_output_tokens must be a positive integer")
        backend_payload["max_tokens"] = max_output_tokens

    text_options = payload.get("text")
    if isinstance(text_options, dict):
        response_format = text_options.get("format")
        if isinstance(response_format, dict):
            backend_payload["response_format"] = response_format

    return backend_payload


def _build_chat_messages(payload: dict[str, object]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    instructions = payload.get("instructions")
    if instructions is not None:
        if not isinstance(instructions, str) or not instructions.strip():
            raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "instructions must be a non-empty string when provided")
        messages.append({"role": "system", "content": instructions})

    input_value = payload.get("input")
    if input_value is None:
        return messages
    if isinstance(input_value, (str, dict)):
        messages.extend(_messages_from_input_item(input_value))
        return messages
    if isinstance(input_value, list):
        for item in input_value:
            messages.extend(_messages_from_input_item(item))
        return messages
    raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "input must be a string, object, or list")


def _messages_from_input_item(item: object) -> list[dict[str, str]]:
    if isinstance(item, str):
        if not item:
            return []
        return [{"role": "user", "content": item}]

    if not isinstance(item, dict):
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "input items must be strings or objects")

    role_value = item.get("role")
    if role_value is None and item.get("type") == "message":
        role_value = item.get("role")

    if isinstance(role_value, str):
        content = _extract_text_content(item.get("content"))
        if content is None:
            raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"message content for role '{role_value}' must be textual")
        return [{"role": _normalize_role(role_value), "content": content}]

    item_type = item.get("type")
    if isinstance(item_type, str):
        if item_type in {"input_image", "image", "input_audio", "audio"}:
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                f"unsupported input item type '{item_type}'; only text generation is implemented in v1",
            )
        if item_type in {"input_text", "output_text", "text"}:
            content = _extract_text_content(item)
            if content is None:
                raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"input item '{item_type}' must contain text")
            role = "assistant" if item_type == "output_text" else "user"
            return [{"role": role, "content": content}]

    content = _extract_text_content(item.get("content"))
    if content is not None:
        return [{"role": "user", "content": content}]

    raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "unsupported input item shape for text-only inference")


def _normalize_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "developer":
        return "system"
    if normalized in {"system", "user", "assistant"}:
        return normalized
    return normalized or "user"


def _extract_text_content(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            item_text = _extract_text_content(item)
            if item_text is None:
                continue
            parts.append(item_text)
        return "\n".join(parts) if parts else None
    if isinstance(value, dict):
        item_type = value.get("type")
        if item_type in {"input_image", "image", "input_audio", "audio"}:
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                f"unsupported content item type '{item_type}'; only text generation is implemented in v1",
            )
        for field_name in ("text", "value"):
            field_value = value.get(field_name)
            if isinstance(field_value, str):
                return field_value
        nested_content = value.get("content")
        if nested_content is not None:
            return _extract_text_content(nested_content)
    return None


def _invoke_backend_chat_completion(
    runtime: HostRuntimeState,
    service: HostServiceConfig,
    payload: dict[str, object],
) -> dict[str, object]:
    backend_base_url = (
        runtime.backend_process.base_url
        if runtime.backend_process is not None
        else service.normalized().backend_base_url
    )
    url = f"{backend_base_url}{CHAT_COMPLETIONS_ENDPOINT}"
    body = json.dumps(payload).encode("utf-8")
    backend_request = request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(backend_request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = _read_upstream_error(exc)
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            f"backend chat completion request failed with status {exc.code}: {detail}",
            error_type="server_error",
        ) from exc
    except error.URLError as exc:
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            f"failed to reach backend inference service: {exc.reason}",
            error_type="server_error",
        ) from exc
    except OSError as exc:
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            f"backend inference request failed: {exc}",
            error_type="server_error",
        ) from exc

    try:
        decoded = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            f"backend returned invalid JSON: {exc}",
            error_type="server_error",
        ) from exc
    if not isinstance(decoded, dict):
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend returned a non-object JSON payload",
            error_type="server_error",
        )
    return decoded


def _read_upstream_error(exc: error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:  # pragma: no cover - defensive path for stdlib HTTPError edge cases
        return exc.reason or "upstream error"
    if not body.strip():
        return exc.reason or "upstream error"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip().splitlines()[0][:400]
    if isinstance(payload, dict):
        error_payload = payload.get("error")
        if isinstance(error_payload, dict):
            message = error_payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    return body.strip().splitlines()[0][:400]


def _build_open_responses_payload(
    request_payload: dict[str, object],
    *,
    model_name: str,
    backend_response: dict[str, object],
) -> dict[str, object]:
    output_text = _extract_backend_output_text(backend_response)
    usage_payload = _translate_usage_payload(backend_response.get("usage"))
    response_id = f"resp_{uuid4().hex}"
    message_id = f"msg_{uuid4().hex}"
    created_at = _response_timestamp(backend_response.get("created"))

    payload: dict[str, object] = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "model": model_name,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": output_text,
        "usage": usage_payload,
        "error": None,
        "incomplete_details": None,
        "instructions": request_payload.get("instructions"),
        "max_output_tokens": request_payload.get("max_output_tokens"),
        "metadata": request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {},
        "parallel_tool_calls": False,
        "temperature": request_payload.get("temperature"),
        "text": request_payload.get("text") if isinstance(request_payload.get("text"), dict) else None,
        "tool_choice": "none",
        "tools": [],
        "top_p": request_payload.get("top_p"),
        "truncation": "disabled",
    }
    return payload


def _extract_backend_output_text(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend response did not contain any completion choices",
            error_type="server_error",
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend completion choice had an invalid shape",
            error_type="server_error",
        )

    message = first_choice.get("message")
    if isinstance(message, dict):
        content = _extract_text_content(message.get("content"))
        if content is not None:
            return content

    text = first_choice.get("text")
    if isinstance(text, str):
        return text

    raise ResponsesProxyError(
        HTTPStatus.BAD_GATEWAY,
        "backend response did not contain assistant text output",
        error_type="server_error",
    )


def _translate_usage_payload(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    input_tokens = _coerce_non_negative_int(value.get("prompt_tokens"))
    output_tokens = _coerce_non_negative_int(value.get("completion_tokens"))
    total_tokens = _coerce_non_negative_int(value.get("total_tokens"))
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _coerce_non_negative_int(value: object) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _response_timestamp(value: object) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return int(time.time())
