"""Open Responses translation and backend proxy helpers."""

from __future__ import annotations

from copy import deepcopy
import json
import time
from dataclasses import dataclass
from http import HTTPStatus
from threading import Lock
from typing import Any, Iterator
from urllib import error, request
from uuid import uuid4

from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import (
    DEFAULT_RESPONSE_STATE_RETENTION_LIMIT,
    HostRuntimeState,
    HostStateError,
    HostStateStore,
    StoredResponseState,
)

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


@dataclass(frozen=True)
class ResponsesConversationState:
    """One stored conversation prefix for Responses follow-up requests."""

    model_name: str
    messages: tuple[dict[str, object], ...]


class ResponsesStateCache:
    """Thread-safe in-memory storage for recent Responses state."""

    def __init__(
        self,
        store: HostStateStore | None = None,
        *,
        retention_limit: int = DEFAULT_RESPONSE_STATE_RETENTION_LIMIT,
    ) -> None:
        self._lock = Lock()
        self._responses: dict[str, ResponsesConversationState] = {}
        self._store = store
        self._retention_limit = retention_limit

    def save(self, response_id: str, model_name: str, messages: list[dict[str, object]]) -> None:
        stored_state = ResponsesConversationState(
            model_name=model_name,
            messages=tuple(_clone_message(message) for message in messages),
        )
        with self._lock:
            self._responses[response_id] = stored_state
        if self._store is not None:
            try:
                self._store.save_response_state(
                    response_id,
                    model_name,
                    [_clone_message(message) for message in messages],
                    retention_limit=self._retention_limit,
                )
            except HostStateError as exc:
                raise ResponsesProxyError(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"failed to persist response state: {exc}",
                    error_type="server_error",
                ) from exc

    def load(self, response_id: str) -> ResponsesConversationState | None:
        with self._lock:
            cached_state = self._responses.get(response_id)
        if cached_state is not None:
            return cached_state
        if self._store is None:
            return None
        try:
            stored_state = self._store.load_response_state(response_id)
        except HostStateError as exc:
            raise ResponsesProxyError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"failed to load persisted response state: {exc}",
                error_type="server_error",
            ) from exc
        if stored_state is None:
            return None
        hydrated_state = _conversation_state_from_stored_state(stored_state)
        with self._lock:
            self._responses[response_id] = hydrated_state
        return hydrated_state


@dataclass(frozen=True)
class PreparedResponseTools:
    """Validated Responses function-tool configuration for one request."""

    response_tools: tuple[dict[str, object], ...]
    backend_tools: tuple[dict[str, object], ...]
    response_tool_choice: str | dict[str, object]
    backend_tool_choice: str | dict[str, object] | None
    parallel_tool_calls: bool


@dataclass
class _StreamingToolCallState:
    index: int
    output_index: int
    item_id: str
    call_id: str
    name: str
    arguments: str = ""
    added_emitted: bool = False
    done_emitted: bool = False

    def in_progress_item(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "type": "function_call",
            "status": "in_progress",
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
        }

    def completed_item(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
        }

    def as_backend_tool_call(self) -> dict[str, object]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


class _StreamingToolCallStateCollection:
    def __init__(self, *, response_id: str) -> None:
        self.response_id = response_id
        self._ordered_states: list[_StreamingToolCallState] = []
        self._states_by_index: dict[int, _StreamingToolCallState] = {}

    def apply_backend_chunk(self, payload: dict[str, object]) -> list[dict[str, object]]:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return []
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                "backend stream choice had an invalid shape",
                error_type="server_error",
            )
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            return []
        raw_tool_calls = delta.get("tool_calls")
        if raw_tool_calls is None:
            return []
        if not isinstance(raw_tool_calls, list):
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                "backend stream tool_calls payload had an invalid shape",
                error_type="server_error",
            )

        events: list[dict[str, object]] = []
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise ResponsesProxyError(
                    HTTPStatus.BAD_GATEWAY,
                    "backend stream tool_call entry had an invalid shape",
                    error_type="server_error",
                )
            state = self._state_from_delta(raw_tool_call)
            if not state.added_emitted:
                events.append(
                    {
                        "type": "response.output_item.added",
                        "response_id": self.response_id,
                        "output_index": state.output_index,
                        "item": state.in_progress_item(),
                    }
                )
                state.added_emitted = True

            delta_arguments = _extract_stream_tool_argument_delta(raw_tool_call)
            if delta_arguments:
                state.arguments += delta_arguments
                events.append(
                    {
                        "type": "response.function_call_arguments.delta",
                        "response_id": self.response_id,
                        "item_id": state.item_id,
                        "output_index": state.output_index,
                        "delta": delta_arguments,
                    }
                )
        return events

    def finish(self) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for state in self._ordered_states:
            if state.done_emitted:
                continue
            events.append(
                {
                    "type": "response.function_call_arguments.done",
                    "response_id": self.response_id,
                    "item_id": state.item_id,
                    "output_index": state.output_index,
                    "arguments": state.arguments,
                }
            )
            events.append(
                {
                    "type": "response.output_item.done",
                    "response_id": self.response_id,
                    "output_index": state.output_index,
                    "item": state.completed_item(),
                }
            )
            state.done_emitted = True
        return events

    def as_backend_tool_calls(self) -> list[dict[str, object]]:
        return [state.as_backend_tool_call() for state in self._ordered_states]

    def _state_from_delta(self, payload: dict[str, object]) -> _StreamingToolCallState:
        index_value = payload.get("index", 0)
        if not isinstance(index_value, int) or index_value < 0:
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                "backend stream tool_call index must be a non-negative integer",
                error_type="server_error",
            )
        existing = self._states_by_index.get(index_value)
        if existing is not None:
            call_id = payload.get("id")
            if isinstance(call_id, str) and call_id.strip():
                existing.call_id = call_id.strip()
            function_payload = payload.get("function")
            if isinstance(function_payload, dict):
                function_name = function_payload.get("name")
                if isinstance(function_name, str) and function_name.strip():
                    existing.name = _merge_stream_tool_name(existing.name, function_name.strip())
            return existing

        call_id = payload.get("id")
        function_payload = payload.get("function")
        function_name = function_payload.get("name") if isinstance(function_payload, dict) else None
        state = _StreamingToolCallState(
            index=index_value,
            output_index=index_value,
            item_id=f"fc_{uuid4().hex}",
            call_id=(call_id.strip() if isinstance(call_id, str) and call_id.strip() else f"call_{uuid4().hex}"),
            name=(function_name.strip() if isinstance(function_name, str) and function_name.strip() else ""),
        )
        self._ordered_states.append(state)
        self._states_by_index[index_value] = state
        return state


@dataclass
class ResponsesStreamSession:
    """One live streaming Open Responses proxy session."""

    request_payload: dict[str, object]
    model_name: str
    response_id: str
    message_id: str
    created_at: int
    upstream_response: Any
    backend_messages: list[dict[str, object]]
    response_tools: tuple[dict[str, object], ...]
    response_tool_choice: str | dict[str, object]
    parallel_tool_calls: bool
    response_state_cache: ResponsesStateCache | None
    _closed: bool = False

    def iter_events(self) -> Iterator[dict[str, object]]:
        """Yield translated Open Responses SSE events."""
        yield {
            "type": "response.created",
            "response": _build_in_progress_responses_payload(
                self.request_payload,
                model_name=self.model_name,
                response_id=self.response_id,
                created_at=self.created_at,
                response_tools=self.response_tools,
                response_tool_choice=self.response_tool_choice,
                parallel_tool_calls=self.parallel_tool_calls,
            ),
        }

        output_parts: list[str] = []
        tool_calls = _StreamingToolCallStateCollection(response_id=self.response_id)
        usage_value: object = None
        created_at = self.created_at

        try:
            for backend_chunk in _iter_backend_chat_completion_stream(self.upstream_response):
                chunk_created = backend_chunk.get("created")
                if isinstance(chunk_created, int) and chunk_created > 0:
                    created_at = chunk_created

                chunk_usage = backend_chunk.get("usage")
                if isinstance(chunk_usage, dict):
                    usage_value = chunk_usage

                for event in tool_calls.apply_backend_chunk(backend_chunk):
                    yield event

                delta = _extract_backend_delta_text(backend_chunk)
                if not delta:
                    continue

                output_parts.append(delta)
                yield {
                    "type": "response.output_text.delta",
                    "response_id": self.response_id,
                    "item_id": self.message_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": delta,
                }
        except ResponsesProxyError as exc:
            yield _stream_error_event(exc)
            return
        finally:
            self.close()

        output_text = "".join(output_parts)
        if output_text:
            yield {
                "type": "response.output_text.done",
                "response_id": self.response_id,
                "item_id": self.message_id,
                "output_index": 0,
                "content_index": 0,
                "text": output_text,
            }
        for event in tool_calls.finish():
            yield event

        tool_call_payloads = tool_calls.as_backend_tool_calls()
        backend_response = _synthesize_backend_response(
            model_name=self.model_name,
            created_at=created_at,
            output_text=output_text,
            usage_value=usage_value,
            tool_calls=tool_call_payloads,
        )
        if self.response_state_cache is not None:
            assistant_message = _build_backend_assistant_message(backend_response)
            self.response_state_cache.save(
                self.response_id,
                self.model_name,
                [*self.backend_messages, assistant_message],
            )
        yield {
            "type": "response.completed",
            "response": _build_open_responses_payload(
                self.request_payload,
                model_name=self.model_name,
                backend_response=backend_response,
                response_tools=self.response_tools,
                response_tool_choice=self.response_tool_choice,
                parallel_tool_calls=self.parallel_tool_calls,
                response_id=self.response_id,
                message_id=self.message_id,
                created_at=created_at,
            ),
        }

    def close(self) -> None:
        """Close the upstream backend response if it is still open."""
        if self._closed:
            return
        close = getattr(self.upstream_response, "close", None)
        if callable(close):
            close()
        self._closed = True


def proxy_responses_request(
    store: HostStateStore,
    service: HostServiceConfig,
    payload: dict[str, object],
    *,
    response_state_cache: ResponsesStateCache | None = None,
) -> dict[str, object]:
    """Proxy one Open Responses request to the running llama-server backend."""
    runtime = store.load_runtime_state()
    model_name = _resolve_requested_model(runtime, payload)
    if is_streaming_request(payload):
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "streaming requests must use the streaming control-plane path",
        )
    prepared_tools = _prepare_response_tools(payload)
    previous_state = _load_previous_response_state(payload, response_state_cache)
    if previous_state is not None and previous_state.model_name != model_name:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            f"previous_response_id targets model '{previous_state.model_name}', not active model '{model_name}'",
        )
    backend_messages = _build_chat_messages(payload, previous_state=previous_state)
    backend_payload = _build_backend_chat_payload(
        payload,
        model_name=model_name,
        stream=False,
        messages=backend_messages,
        backend_tools=prepared_tools.backend_tools,
        backend_tool_choice=prepared_tools.backend_tool_choice,
        parallel_tool_calls=prepared_tools.parallel_tool_calls,
    )
    backend_response = _invoke_backend_chat_completion(runtime, service, backend_payload)
    response_payload = _build_open_responses_payload(
        payload,
        model_name=model_name,
        backend_response=backend_response,
        response_tools=prepared_tools.response_tools,
        response_tool_choice=prepared_tools.response_tool_choice,
        parallel_tool_calls=prepared_tools.parallel_tool_calls,
    )
    if response_state_cache is not None:
        assistant_message = _build_backend_assistant_message(backend_response)
        response_state_cache.save(
            str(response_payload["id"]),
            model_name,
            [*backend_messages, assistant_message],
        )
    return response_payload


def open_responses_stream(
    store: HostStateStore,
    service: HostServiceConfig,
    payload: dict[str, object],
    *,
    response_state_cache: ResponsesStateCache | None = None,
) -> ResponsesStreamSession:
    """Open one streaming Responses session against the running backend."""
    if not is_streaming_request(payload):
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "streaming request must set stream=true")

    runtime = store.load_runtime_state()
    model_name = _resolve_requested_model(runtime, payload)
    prepared_tools = _prepare_response_tools(payload)
    previous_state = _load_previous_response_state(payload, response_state_cache)
    if previous_state is not None and previous_state.model_name != model_name:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            f"previous_response_id targets model '{previous_state.model_name}', not active model '{model_name}'",
        )
    backend_messages = _build_chat_messages(payload, previous_state=previous_state)
    backend_payload = _build_backend_chat_payload(
        payload,
        model_name=model_name,
        stream=True,
        messages=backend_messages,
        backend_tools=prepared_tools.backend_tools,
        backend_tool_choice=prepared_tools.backend_tool_choice,
        parallel_tool_calls=prepared_tools.parallel_tool_calls,
    )
    upstream_response = _open_backend_chat_completion_stream(runtime, service, backend_payload)
    return ResponsesStreamSession(
        request_payload=payload,
        model_name=model_name,
        response_id=f"resp_{uuid4().hex}",
        message_id=f"msg_{uuid4().hex}",
        created_at=int(time.time()),
        upstream_response=upstream_response,
        backend_messages=backend_messages,
        response_tools=prepared_tools.response_tools,
        response_tool_choice=prepared_tools.response_tool_choice,
        parallel_tool_calls=prepared_tools.parallel_tool_calls,
        response_state_cache=response_state_cache,
    )


def parse_json_request_body(body: bytes) -> dict[str, object]:
    """Decode one JSON request body into an object payload."""
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"invalid JSON request body: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "request body must be a JSON object")
    return decoded


def is_streaming_request(payload: dict[str, object]) -> bool:
    """Validate and return whether one Responses request is streaming."""
    stream = payload.get("stream")
    if stream is None or stream is False:
        return False
    if stream is True:
        return True
    raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "stream must be a boolean when provided")


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
    stream: bool,
    messages: list[dict[str, object]],
    backend_tools: tuple[dict[str, object], ...],
    backend_tool_choice: str | dict[str, object] | None,
    parallel_tool_calls: bool,
) -> dict[str, object]:
    if not messages:
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "input or instructions must produce at least one text message")

    backend_payload: dict[str, object] = {
        "model": model_name,
        "messages": messages,
        "stream": stream,
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

    if backend_tools:
        backend_payload["tools"] = list(backend_tools)
        backend_payload["parallel_tool_calls"] = parallel_tool_calls
        if backend_tool_choice is not None:
            backend_payload["tool_choice"] = backend_tool_choice

    return backend_payload


def _build_chat_messages(
    payload: dict[str, object],
    *,
    previous_state: ResponsesConversationState | None,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    available_tool_call_ids: set[str] = set()

    if previous_state is not None:
        messages.extend(_clone_message(message) for message in previous_state.messages)
        available_tool_call_ids.update(_tool_call_ids_from_messages(messages))

    instructions = payload.get("instructions")
    if instructions is not None:
        if not isinstance(instructions, str) or not instructions.strip():
            raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "instructions must be a non-empty string when provided")
        messages.append({"role": "system", "content": instructions})

    input_value = payload.get("input")
    if input_value is None:
        return messages
    if isinstance(input_value, (str, dict)):
        messages.extend(_messages_from_input_item(input_value, available_tool_call_ids))
        return messages
    if isinstance(input_value, list):
        for item in input_value:
            messages.extend(_messages_from_input_item(item, available_tool_call_ids))
        return messages
    raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "input must be a string, object, or list")


def _messages_from_input_item(item: object, available_tool_call_ids: set[str]) -> list[dict[str, object]]:
    if isinstance(item, str):
        if not item:
            return []
        return [{"role": "user", "content": item}]

    if not isinstance(item, dict):
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "input items must be strings or objects")

    item_type = item.get("type")
    if item_type == "function_call":
        return [_build_assistant_tool_call_message(item, available_tool_call_ids)]
    if item_type == "function_call_output":
        return [_build_tool_result_message(item, available_tool_call_ids)]

    role_value = item.get("role")
    if role_value is None and item.get("type") == "message":
        role_value = item.get("role")

    if isinstance(role_value, str):
        normalized_role = _normalize_role(role_value)
        content = _extract_text_content(item.get("content"))
        tool_calls = _normalize_message_tool_calls(item.get("tool_calls"), available_tool_call_ids)
        if content is None and not tool_calls:
            raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"message content for role '{role_value}' must be textual")
        if tool_calls and normalized_role != "assistant":
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                f"message role '{normalized_role}' cannot contain tool_calls",
            )
        message: dict[str, object] = {"role": normalized_role}
        if content is not None:
            message["content"] = content
        if tool_calls:
            message["tool_calls"] = tool_calls
        return [message]

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


def _prepare_response_tools(payload: dict[str, object]) -> PreparedResponseTools:
    tools_value = payload.get("tools")
    response_tools, backend_tools = _normalize_function_tools(tools_value)

    parallel_tool_calls_value = payload.get("parallel_tool_calls")
    if parallel_tool_calls_value is None:
        parallel_tool_calls = False
    elif isinstance(parallel_tool_calls_value, bool):
        parallel_tool_calls = parallel_tool_calls_value
    else:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "parallel_tool_calls must be a boolean when provided",
        )
    if parallel_tool_calls and not response_tools:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "parallel_tool_calls requires at least one function tool",
        )

    tool_choice_value = payload.get("tool_choice")
    response_tool_choice, backend_tool_choice = _normalize_tool_choice(tool_choice_value, response_tools)

    return PreparedResponseTools(
        response_tools=tuple(response_tools),
        backend_tools=tuple(backend_tools),
        response_tool_choice=response_tool_choice,
        backend_tool_choice=backend_tool_choice,
        parallel_tool_calls=parallel_tool_calls,
    )


def _normalize_function_tools(value: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if value is None:
        return [], []
    if not isinstance(value, list):
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, "tools must be a list when provided")

    response_tools: list[dict[str, object]] = []
    backend_tools: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"tool at index {index} must be an object")
        if item.get("type") != "function":
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                "only function tools are implemented in v1",
            )
        function_payload = item.get("function")
        tool_name = item.get("name")
        tool_description = item.get("description")
        tool_parameters = item.get("parameters")
        tool_strict = item.get("strict")
        if isinstance(function_payload, dict):
            tool_name = function_payload.get("name", tool_name)
            tool_description = function_payload.get("description", tool_description)
            tool_parameters = function_payload.get("parameters", tool_parameters)
            tool_strict = function_payload.get("strict", tool_strict)

        normalized_name = _required_non_empty_string(tool_name, field_name=f"tools[{index}].name")
        if tool_description is not None and not isinstance(tool_description, str):
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                f"tools[{index}].description must be a string when provided",
            )
        if tool_parameters is None:
            tool_parameters = {"type": "object", "properties": {}, "additionalProperties": False}
        if not isinstance(tool_parameters, dict):
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                f"tools[{index}].parameters must be an object when provided",
            )
        if tool_strict is not None and not isinstance(tool_strict, bool):
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                f"tools[{index}].strict must be a boolean when provided",
            )

        response_tool = {
            "type": "function",
            "name": normalized_name,
            "description": tool_description if isinstance(tool_description, str) else "",
            "parameters": tool_parameters,
            "strict": tool_strict if isinstance(tool_strict, bool) else False,
        }
        backend_tool = {
            "type": "function",
            "function": {
                "name": normalized_name,
                "description": tool_description if isinstance(tool_description, str) else "",
                "parameters": tool_parameters,
            },
        }
        response_tools.append(response_tool)
        backend_tools.append(backend_tool)
    return response_tools, backend_tools


def _normalize_tool_choice(
    value: object,
    response_tools: list[dict[str, object]],
) -> tuple[str | dict[str, object], str | dict[str, object] | None]:
    tool_names = {str(tool["name"]) for tool in response_tools}

    if value is None:
        if response_tools:
            return "auto", "auto"
        return "none", None

    if isinstance(value, str):
        if value not in {"none", "auto", "required"}:
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                "tool_choice must be one of: none, auto, required",
            )
        if value != "none" and not response_tools:
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                "tool_choice requires at least one function tool",
            )
        return value, value if response_tools else None

    if not isinstance(value, dict):
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "tool_choice must be a string or object when provided",
        )
    if not response_tools:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "tool_choice requires at least one function tool",
        )
    if value.get("type") != "function":
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "only function tool_choice objects are implemented in v1",
        )
    function_payload = value.get("function")
    function_name = value.get("name")
    if isinstance(function_payload, dict):
        function_name = function_payload.get("name", function_name)
    normalized_name = _required_non_empty_string(function_name, field_name="tool_choice.name")
    if normalized_name not in tool_names:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            f"tool_choice references unknown function tool '{normalized_name}'",
        )
    response_tool_choice = {"type": "function", "name": normalized_name}
    backend_tool_choice = {"type": "function", "function": {"name": normalized_name}}
    return response_tool_choice, backend_tool_choice


def _load_previous_response_state(
    payload: dict[str, object],
    response_state_cache: ResponsesStateCache | None,
) -> ResponsesConversationState | None:
    previous_response_id = payload.get("previous_response_id")
    if previous_response_id is None:
        return None
    if not isinstance(previous_response_id, str) or not previous_response_id.strip():
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "previous_response_id must be a non-empty string when provided",
        )
    if response_state_cache is None:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "previous_response_id is not available for this control-plane path",
        )
    state = response_state_cache.load(previous_response_id.strip())
    if state is None:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            f"unknown previous_response_id '{previous_response_id.strip()}'; it may have expired, been pruned, or come from a different host instance",
        )
    return state


def _build_assistant_tool_call_message(
    item: dict[str, object],
    available_tool_call_ids: set[str],
) -> dict[str, object]:
    call_id = _required_non_empty_string(item.get("call_id"), field_name="input.function_call.call_id")
    name = _required_non_empty_string(item.get("name"), field_name="input.function_call.name")
    arguments = _normalize_json_string(item.get("arguments"), field_name="input.function_call.arguments")
    available_tool_call_ids.add(call_id)
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        ],
    }


def _build_tool_result_message(
    item: dict[str, object],
    available_tool_call_ids: set[str],
) -> dict[str, object]:
    call_id = _required_non_empty_string(item.get("call_id"), field_name="input.function_call_output.call_id")
    if call_id not in available_tool_call_ids:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            f"function_call_output for call_id '{call_id}' requires previous_response_id or a prior function_call item",
        )
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": _stringify_tool_output(item.get("output")),
    }


def _normalize_message_tool_calls(
    value: object,
    available_tool_call_ids: set[str],
) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            "message tool_calls must be a list when provided",
        )

    tool_calls: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                f"message tool_calls[{index}] must be an object",
            )
        if item.get("type") != "function":
            raise ResponsesProxyError(
                HTTPStatus.BAD_REQUEST,
                "only function tool_calls are implemented in v1",
            )
        function_payload = item.get("function")
        function_name = item.get("name")
        function_arguments = item.get("arguments")
        if isinstance(function_payload, dict):
            function_name = function_payload.get("name", function_name)
            function_arguments = function_payload.get("arguments", function_arguments)
        call_id = _required_non_empty_string(
            item.get("call_id", item.get("id")),
            field_name=f"message.tool_calls[{index}].call_id",
        )
        available_tool_call_ids.add(call_id)
        tool_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": _required_non_empty_string(
                        function_name,
                        field_name=f"message.tool_calls[{index}].name",
                    ),
                    "arguments": _normalize_json_string(
                        function_arguments,
                        field_name=f"message.tool_calls[{index}].arguments",
                    ),
                },
            }
        )
    return tool_calls


def _tool_call_ids_from_messages(messages: list[dict[str, object]]) -> set[str]:
    identifiers: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            call_id = tool_call.get("id")
            if isinstance(call_id, str) and call_id:
                identifiers.add(call_id)
    return identifiers


def _clone_message(message: dict[str, object]) -> dict[str, object]:
    return deepcopy(message)


def _conversation_state_from_stored_state(state: StoredResponseState) -> ResponsesConversationState:
    return ResponsesConversationState(
        model_name=state.model_name,
        messages=tuple(_clone_message(message) for message in state.messages),
    )


def _required_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResponsesProxyError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a non-empty string")
    return value.strip()


def _normalize_json_string(value: object, *, field_name: str) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except TypeError as exc:
        raise ResponsesProxyError(
            HTTPStatus.BAD_REQUEST,
            f"{field_name} must be a string or JSON-serializable value",
        ) from exc


def _stringify_tool_output(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value)
    except TypeError:
        return str(value)


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


def _open_backend_chat_completion_stream(
    runtime: HostRuntimeState,
    service: HostServiceConfig,
    payload: dict[str, object],
) -> Any:
    backend_request = _build_backend_request(runtime, service, payload)
    try:
        return request.urlopen(backend_request, timeout=30)
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


def _build_backend_request(
    runtime: HostRuntimeState,
    service: HostServiceConfig,
    payload: dict[str, object],
) -> request.Request:
    backend_base_url = (
        runtime.backend_process.base_url
        if runtime.backend_process is not None
        else service.normalized().backend_base_url
    )
    url = f"{backend_base_url}{CHAT_COMPLETIONS_ENDPOINT}"
    body = json.dumps(payload).encode("utf-8")
    return request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )


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


def _iter_backend_chat_completion_stream(upstream_response: Any) -> Iterator[dict[str, object]]:
    for data in _iter_sse_data_frames(upstream_response):
        if data == "[DONE]":
            return
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                f"backend returned invalid streaming JSON: {exc}",
                error_type="server_error",
            ) from exc
        if not isinstance(decoded, dict):
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                "backend returned a non-object JSON stream chunk",
                error_type="server_error",
            )
        yield decoded


def _iter_sse_data_frames(upstream_response: Any) -> Iterator[str]:
    pending_data: list[str] = []
    try:
        iterator = iter(upstream_response)
        for raw_line in iterator:
            try:
                line = raw_line.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError as exc:
                raise ResponsesProxyError(
                    HTTPStatus.BAD_GATEWAY,
                    f"backend returned invalid UTF-8 in streaming response: {exc}",
                    error_type="server_error",
                ) from exc

            if not line:
                if pending_data:
                    yield "\n".join(pending_data)
                    pending_data = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                pending_data.append(line[5:].lstrip())
        if pending_data:
            yield "\n".join(pending_data)
    except OSError as exc:
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            f"failed while reading backend streaming response: {exc}",
            error_type="server_error",
        ) from exc


def _build_open_responses_payload(
    request_payload: dict[str, object],
    *,
    model_name: str,
    backend_response: dict[str, object],
    response_tools: tuple[dict[str, object], ...] = (),
    response_tool_choice: str | dict[str, object] = "none",
    parallel_tool_calls: bool = False,
    response_id: str | None = None,
    message_id: str | None = None,
    created_at: int | None = None,
) -> dict[str, object]:
    output_items, output_text = _build_output_items_from_backend_response(
        backend_response,
        message_id=message_id,
    )
    usage_payload = _translate_usage_payload(backend_response.get("usage"))
    resolved_response_id = response_id or f"resp_{uuid4().hex}"
    resolved_created_at = created_at or _response_timestamp(backend_response.get("created"))

    payload: dict[str, object] = {
        "id": resolved_response_id,
        "object": "response",
        "created_at": resolved_created_at,
        "status": "completed",
        "model": model_name,
        "output": output_items,
        "output_text": output_text,
        "usage": usage_payload,
        "error": None,
        "incomplete_details": None,
        "instructions": request_payload.get("instructions"),
        "max_output_tokens": request_payload.get("max_output_tokens"),
        "metadata": request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {},
        "parallel_tool_calls": parallel_tool_calls,
        "temperature": request_payload.get("temperature"),
        "text": request_payload.get("text") if isinstance(request_payload.get("text"), dict) else None,
        "tool_choice": response_tool_choice,
        "tools": list(response_tools),
        "top_p": request_payload.get("top_p"),
        "truncation": "disabled",
    }
    return payload


def _build_output_items_from_backend_response(
    payload: dict[str, object],
    *,
    message_id: str | None,
) -> tuple[list[dict[str, object]], str]:
    assistant_message = _build_backend_assistant_message(payload)
    output_items: list[dict[str, object]] = []
    output_text = ""

    content = assistant_message.get("content")
    if content is not None:
        output_text = _extract_text_content(content) or ""
        output_items.append(
            {
                "id": message_id or f"msg_{uuid4().hex}",
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
        )

    for tool_call in _extract_backend_tool_calls(assistant_message):
        output_items.append(
            {
                "id": f"fc_{uuid4().hex}",
                "type": "function_call",
                "status": "completed",
                "call_id": tool_call["id"],
                "name": tool_call["name"],
                "arguments": tool_call["arguments"],
            }
        )

    if not output_items:
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend response did not contain assistant text or function tool calls",
            error_type="server_error",
        )
    return output_items, output_text


def _build_backend_assistant_message(payload: dict[str, object]) -> dict[str, object]:
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
        normalized_message: dict[str, object] = {"role": "assistant"}
        if message.get("content") is not None:
            normalized_message["content"] = message.get("content")
        tool_calls = _extract_backend_tool_calls(message)
        if tool_calls:
            normalized_message["tool_calls"] = [
                {
                    "id": tool_call["id"],
                    "type": "function",
                    "function": {
                        "name": tool_call["name"],
                        "arguments": tool_call["arguments"],
                    },
                }
                for tool_call in tool_calls
            ]
        if "content" in normalized_message or "tool_calls" in normalized_message:
            return normalized_message

    text = first_choice.get("text")
    if isinstance(text, str):
        return {"role": "assistant", "content": text}

    raise ResponsesProxyError(
        HTTPStatus.BAD_GATEWAY,
        "backend response did not contain assistant text or function tool calls",
        error_type="server_error",
    )


def _extract_backend_delta_text(payload: dict[str, object]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        if isinstance(payload.get("usage"), dict):
            return None
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend stream chunk did not contain any completion choices",
            error_type="server_error",
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend stream choice had an invalid shape",
            error_type="server_error",
        )

    delta = first_choice.get("delta")
    if isinstance(delta, dict):
        content = _extract_text_content(delta.get("content"))
        if content is not None:
            return content

    message = first_choice.get("message")
    if isinstance(message, dict):
        content = _extract_text_content(message.get("content"))
        if content is not None:
            return content

    text = first_choice.get("text")
    if isinstance(text, str):
        return text

    return None


def _extract_backend_tool_calls(message: object) -> list[dict[str, str]]:
    if not isinstance(message, dict):
        return []
    raw_tool_calls = message.get("tool_calls")
    if raw_tool_calls is None:
        return []
    if not isinstance(raw_tool_calls, list):
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend tool_calls payload had an invalid shape",
            error_type="server_error",
        )

    tool_calls: list[dict[str, str]] = []
    for index, item in enumerate(raw_tool_calls):
        if not isinstance(item, dict):
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                f"backend tool_call at index {index} had an invalid shape",
                error_type="server_error",
            )
        if item.get("type") != "function":
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                "backend returned a non-function tool call, which is unsupported in v1",
                error_type="server_error",
            )
        function_payload = item.get("function")
        if not isinstance(function_payload, dict):
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                "backend tool_call function payload had an invalid shape",
                error_type="server_error",
            )
        tool_call_id = item.get("id")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            tool_call_id = f"call_{uuid4().hex}"
        function_name = function_payload.get("name")
        if not isinstance(function_name, str) or not function_name.strip():
            raise ResponsesProxyError(
                HTTPStatus.BAD_GATEWAY,
                "backend tool_call did not include a valid function name",
                error_type="server_error",
            )
        tool_calls.append(
            {
                "id": tool_call_id,
                "name": function_name.strip(),
                "arguments": _normalize_backend_arguments(function_payload.get("arguments")),
            }
        )
    return tool_calls


def _build_in_progress_responses_payload(
    request_payload: dict[str, object],
    *,
    model_name: str,
    response_id: str,
    created_at: int,
    response_tools: tuple[dict[str, object], ...],
    response_tool_choice: str | dict[str, object],
    parallel_tool_calls: bool,
) -> dict[str, object]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "in_progress",
        "model": model_name,
        "output": [],
        "output_text": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "error": None,
        "incomplete_details": None,
        "instructions": request_payload.get("instructions"),
        "max_output_tokens": request_payload.get("max_output_tokens"),
        "metadata": request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {},
        "parallel_tool_calls": parallel_tool_calls,
        "temperature": request_payload.get("temperature"),
        "text": request_payload.get("text") if isinstance(request_payload.get("text"), dict) else None,
        "tool_choice": response_tool_choice,
        "tools": list(response_tools),
        "top_p": request_payload.get("top_p"),
        "truncation": "disabled",
    }


def _synthesize_backend_response(
    *,
    model_name: str,
    created_at: int,
    output_text: str,
    usage_value: object,
    tool_calls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant"}
    if output_text:
        message["content"] = output_text
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "object": "chat.completion",
        "model": model_name,
        "created": created_at,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if tool_calls else "stop",
                "message": message,
            }
        ],
        "usage": usage_value if isinstance(usage_value, dict) else {},
    }


def _stream_error_event(exc: ResponsesProxyError) -> dict[str, object]:
    payload = exc.to_payload()
    return {
        "type": "error",
        "error": payload["error"],
    }


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


def _normalize_backend_arguments(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "{}"
    try:
        return json.dumps(value)
    except TypeError as exc:
        raise ResponsesProxyError(
            HTTPStatus.BAD_GATEWAY,
            "backend tool_call arguments were not JSON-serializable",
            error_type="server_error",
        ) from exc


def _extract_stream_tool_argument_delta(payload: dict[str, object]) -> str:
    function_payload = payload.get("function")
    if not isinstance(function_payload, dict):
        return ""
    arguments = function_payload.get("arguments")
    return arguments if isinstance(arguments, str) else ""


def _merge_stream_tool_name(current: str, incoming: str) -> str:
    if not current:
        return incoming
    if incoming.startswith(current):
        return incoming
    if current.endswith(incoming):
        return current
    if incoming and incoming != current:
        return current + incoming
    return current
