"""Repo-owned function-tool registry for control-plane execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import Callable

from aistackd.models.sources import ModelSourceError, PRIMARY_MODEL_SOURCE, search_models
from aistackd.runtime.host import HostServiceConfig
from aistackd.state.host import HostStateStore


class RepoOwnedToolError(RuntimeError):
    """Raised when one repo-owned tool invocation is invalid or cannot complete."""


@dataclass(frozen=True)
class RepoOwnedToolInvocationError(RuntimeError):
    """Typed wrapper for tool execution failures surfaced through Responses."""

    status: HTTPStatus
    message: str
    error_type: str = "invalid_request_error"


ToolHandler = Callable[[dict[str, object], HostStateStore, HostServiceConfig], dict[str, object]]


@dataclass(frozen=True)
class RepoOwnedFunctionTool:
    """One repo-owned function tool exposed by the control plane."""

    name: str
    description: str
    parameters: dict[str, object]
    handler: ToolHandler

    def response_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }


def repo_owned_tool_names() -> tuple[str, ...]:
    """Return the canonical ordered list of repo-owned tool names."""
    return tuple(_REPO_OWNED_TOOLS.keys())


def get_repo_owned_tool(name: str) -> RepoOwnedFunctionTool | None:
    """Return one repo-owned tool definition by name."""
    return _REPO_OWNED_TOOLS.get(name)


def canonical_repo_owned_tools(names: list[str] | tuple[str, ...]) -> tuple[dict[str, object], ...]:
    """Return canonical Responses tool definitions for the requested repo-owned tools."""
    definitions: list[dict[str, object]] = []
    for name in names:
        tool = get_repo_owned_tool(name)
        if tool is None:
            known_names = ", ".join(repo_owned_tool_names())
            raise RepoOwnedToolInvocationError(
                HTTPStatus.BAD_REQUEST,
                f"unsupported repo-owned tool '{name}'; expected one of: {known_names}",
            )
        definitions.append(tool.response_definition())
    return tuple(definitions)


def execute_repo_owned_tool_call(
    *,
    name: str,
    arguments_json: str,
    call_id: str,
    store: HostStateStore,
    service: HostServiceConfig,
) -> dict[str, object]:
    """Execute one repo-owned function tool and return a backend tool-result message."""
    tool = get_repo_owned_tool(name)
    if tool is None:
        known_names = ", ".join(repo_owned_tool_names())
        raise RepoOwnedToolInvocationError(
            HTTPStatus.BAD_REQUEST,
            f"repo-owned tool execution does not support '{name}'; expected one of: {known_names}",
        )
    arguments = _parse_arguments(arguments_json, tool.name)
    try:
        output = tool.handler(arguments, store, service)
    except RepoOwnedToolError as exc:
        raise RepoOwnedToolInvocationError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(output),
    }


def _parse_arguments(arguments_json: str, tool_name: str) -> dict[str, object]:
    try:
        decoded = json.loads(arguments_json) if arguments_json.strip() else {}
    except json.JSONDecodeError as exc:
        raise RepoOwnedToolError(f"repo-owned tool '{tool_name}' received invalid JSON arguments: {exc}") from exc
    if not isinstance(decoded, dict):
        raise RepoOwnedToolError(f"repo-owned tool '{tool_name}' requires a JSON object for arguments")
    return decoded


def _list_installed_models(arguments: dict[str, object], store: HostStateStore, _service: HostServiceConfig) -> dict[str, object]:
    _require_no_extra_arguments(arguments, "list_installed_models")
    runtime = store.load_runtime_state()
    return {
        "active_model": runtime.active_model,
        "models": [
            {
                "id": record.model,
                "source": record.source,
                "backend": record.backend,
                "acquisition_method": record.acquisition_method,
                "status": record.status,
                "active": record.model == runtime.active_model,
            }
            for record in runtime.installed_models
        ],
    }


def _get_runtime_status(arguments: dict[str, object], store: HostStateStore, service: HostServiceConfig) -> dict[str, object]:
    include_service = arguments.pop("include_service", True)
    if not isinstance(include_service, bool):
        raise RepoOwnedToolError("get_runtime_status.include_service must be a boolean when provided")
    _require_no_extra_arguments(arguments, "get_runtime_status")

    payload: dict[str, object] = {
        "runtime": store.load_runtime_state().to_dict(),
    }
    if include_service:
        payload["service"] = service.normalized().to_dict()
    return payload


def _search_models(arguments: dict[str, object], _store: HostStateStore, _service: HostServiceConfig) -> dict[str, object]:
    query = arguments.pop("query", None)
    llmfit_binary = arguments.pop("llmfit_binary", "llmfit")
    if query is not None and (not isinstance(query, str) or not query.strip()):
        raise RepoOwnedToolError("search_models.query must be a non-empty string when provided")
    if not isinstance(llmfit_binary, str) or not llmfit_binary.strip():
        raise RepoOwnedToolError("search_models.llmfit_binary must be a non-empty string when provided")
    _require_no_extra_arguments(arguments, "search_models")
    try:
        matches = search_models(query.strip() if isinstance(query, str) else None, llmfit_binary=llmfit_binary.strip())
    except (ModelSourceError, ValueError) as exc:
        raise RepoOwnedToolError(str(exc)) from exc
    return {
        "query": query.strip() if isinstance(query, str) else None,
        "source": PRIMARY_MODEL_SOURCE,
        "models": [model.as_dict() for model in matches],
    }


def _require_no_extra_arguments(arguments: dict[str, object], tool_name: str) -> None:
    if arguments:
        unexpected = ", ".join(sorted(arguments))
        raise RepoOwnedToolError(f"{tool_name} does not accept arguments: {unexpected}")


_REPO_OWNED_TOOLS: dict[str, RepoOwnedFunctionTool] = {
    "list_installed_models": RepoOwnedFunctionTool(
        name="list_installed_models",
        description="Return installed host models and the active model.",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=_list_installed_models,
    ),
    "get_runtime_status": RepoOwnedFunctionTool(
        name="get_runtime_status",
        description="Return current host runtime status and service configuration.",
        parameters={
            "type": "object",
            "properties": {
                "include_service": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        handler=_get_runtime_status,
    ),
    "search_models": RepoOwnedFunctionTool(
        name="search_models",
        description="Search the live llmfit catalog for matching models.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "llmfit_binary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        handler=_search_models,
    ),
}

