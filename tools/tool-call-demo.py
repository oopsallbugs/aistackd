#!/usr/bin/env python3
"""Demonstrate one client-managed function-tool loop against /v1/responses."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
import socket
import sys
from urllib import error, request

DEFAULT_ACTIVE_PROFILE = "${active_profile}"
DEFAULT_BASE_URL = "${base_url}"
DEFAULT_API_KEY_ENV = "${api_key_env}"
DEFAULT_MODEL = "${model}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one local tool-calling example where the frontend executes tools and sends function_call_output back.",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Use the get_local_time tool and answer with the current UTC time.",
        help="prompt to send to /v1/responses",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"control-plane base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--api-key-env",
        default=DEFAULT_API_KEY_ENV,
        help=f"environment variable containing the API key (default: {DEFAULT_API_KEY_ENV})",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=4,
        help="maximum tool-call rounds to execute",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        api_key = resolve_api_key(args.api_key_env)
        payload, exit_code = run_demo(args.base_url, api_key, args.prompt, args.max_steps)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return exit_code

    render_text(payload)
    return exit_code


def run_demo(base_url: str, api_key: str, prompt: str, max_steps: int) -> tuple[dict[str, object], int]:
    if max_steps <= 0:
        raise RuntimeError("--max-steps must be a positive integer")

    normalized_base_url = base_url.rstrip("/")
    tool_calls: list[dict[str, object]] = []
    previous_response_id: str | None = None
    pending_input: object = prompt

    for _ in range(max_steps):
        request_payload: dict[str, object] = {
            "input": pending_input,
            "tools": list(tool_definitions()),
            "tool_choice": "auto",
        }
        if previous_response_id is not None:
            request_payload["previous_response_id"] = previous_response_id

        response_payload = post_json(normalized_base_url, "/v1/responses", api_key, request_payload)
        previous_response_id = _require_string(response_payload.get("id"), "response.id")
        output_items = response_payload.get("output")
        if not isinstance(output_items, list):
            raise RuntimeError("responses endpoint returned an invalid output payload")

        function_calls = [item for item in output_items if isinstance(item, dict) and item.get("type") == "function_call"]
        if not function_calls:
            return (
                {
                    "profile": DEFAULT_ACTIVE_PROFILE,
                    "base_url": normalized_base_url,
                    "model": response_payload.get("model", DEFAULT_MODEL),
                    "steps": len(tool_calls) + 1,
                    "tool_calls": tool_calls,
                    "final_output_text": response_payload.get("output_text"),
                    "response": response_payload,
                },
                0,
            )

        follow_up_items: list[dict[str, object]] = []
        for function_call in function_calls:
            call_id = _require_string(function_call.get("call_id"), "function_call.call_id")
            tool_name = _require_string(function_call.get("name"), "function_call.name")
            arguments = parse_tool_arguments(function_call.get("arguments"))
            output = execute_local_tool(tool_name, arguments)
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

    raise RuntimeError(f"tool-call demo exceeded max steps ({max_steps}) without a final assistant message")


def tool_definitions() -> tuple[dict[str, object], ...]:
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
            "description": "Return the frontend hostname and current working directory.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    )


def execute_local_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    if arguments:
        unexpected = ", ".join(sorted(arguments))
        raise RuntimeError(f"local tool '{name}' does not accept arguments: {unexpected}")
    if name == "get_local_time":
        now_local = datetime.now().astimezone()
        now_utc = now_local.astimezone(UTC)
        return {
            "local_iso8601": now_local.isoformat(),
            "utc_iso8601": now_utc.isoformat(),
            "unix_timestamp": int(now_utc.timestamp()),
        }
    if name == "get_frontend_context":
        return {
            "hostname": socket.gethostname(),
            "cwd": os.getcwd(),
            "profile": DEFAULT_ACTIVE_PROFILE,
        }
    raise RuntimeError(f"local tool '{name}' is not implemented in this demo")


def post_json(base_url: str, path: str, api_key: str, payload: dict[str, object]) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(request_object, timeout=30) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"request failed with status {exc.code}: {body.strip() or exc.reason}") from exc
        finally:
            exc.close()
    except error.URLError as exc:
        raise RuntimeError(f"failed to reach {base_url}{path}: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"request failed for {base_url}{path}: {exc}") from exc

    try:
        decoded = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"server returned invalid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("server returned a non-object JSON payload")
    return decoded


def parse_tool_arguments(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            decoded = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"tool call arguments were not valid JSON: {exc}") from exc
    else:
        decoded = value
    if not isinstance(decoded, dict):
        raise RuntimeError("tool call arguments must decode to a JSON object")
    return decoded


def render_text(payload: dict[str, object]) -> None:
    print("tool call demo")
    print(f"profile: {payload.get('profile')}")
    print(f"base_url: {payload.get('base_url')}")
    print(f"model: {payload.get('model')}")
    tool_calls = payload.get("tool_calls")
    print(f"tool_calls: {len(tool_calls) if isinstance(tool_calls, list) else 0}")
    if isinstance(tool_calls, list):
        for entry in tool_calls:
            if not isinstance(entry, dict):
                continue
            print(
                f"call: {entry.get('name')} call_id={entry.get('call_id')} "
                f"output={json.dumps(entry.get('output'), sort_keys=True)}"
            )
    print(f"final_output_text: {payload.get('final_output_text') or ''}")


def resolve_api_key(api_key_env: str) -> str:
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"api key environment variable '{api_key_env}' is not set or empty")
    return api_key


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"missing or invalid {field_name}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
