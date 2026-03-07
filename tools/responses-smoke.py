#!/usr/bin/env python3
"""Smoke-test the configured aistackd Responses API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request

DEFAULT_BASE_URL = "${base_url}"
DEFAULT_API_KEY_ENV = "${api_key_env}"
DEFAULT_PROMPT = "say hello"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test /v1/responses against the configured aistackd control plane.",
    )
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT, help=f"prompt text (default: {DEFAULT_PROMPT!r})")
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
    parser.add_argument("--model", help="optional explicit model; defaults to the active model")
    parser.add_argument("--stream", action="store_true", help="exercise the streaming Responses path")
    parser.add_argument("--max-output-tokens", type=int, help="optional max_output_tokens value")
    parser.add_argument("--timeout", type=float, default=15.0, help="request timeout in seconds")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="output format")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        api_key = resolve_api_key(args.api_key_env)
        payload = build_request_payload(
            args.prompt,
            model=args.model,
            stream=args.stream,
            max_output_tokens=args.max_output_tokens,
        )
        if args.stream:
            result = stream_responses_request(args.base_url, api_key, payload, timeout=args.timeout)
        else:
            result = send_responses_request(args.base_url, api_key, payload, timeout=args.timeout)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        render_text(result)
    return int(result["exit_code"])


def build_request_payload(
    prompt: str,
    *,
    model: str | None,
    stream: bool,
    max_output_tokens: int | None,
) -> dict[str, object]:
    if max_output_tokens is not None and max_output_tokens < 1:
        raise RuntimeError("--max-output-tokens must be a positive integer when provided")
    payload: dict[str, object] = {
        "input": prompt,
        "stream": stream,
    }
    if model:
        payload["model"] = model
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    return payload


def send_responses_request(
    base_url: str,
    api_key: str,
    payload: dict[str, object],
    *,
    timeout: float,
) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url.rstrip('/')}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(request_object, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            status_code = response.status
    except error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"responses request failed with status {exc.code}: {detail.strip() or exc.reason}") from exc
        finally:
            exc.close()
    except error.URLError as exc:
        raise RuntimeError(f"failed to reach {request_object.full_url}: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"responses request failed for {request_object.full_url}: {exc}") from exc

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "exit_code": 2,
            "mode": "non_stream",
            "status_code": status_code,
            "error": f"server returned invalid JSON: {exc}",
        }
    if not isinstance(decoded, dict):
        return {
            "ok": False,
            "exit_code": 2,
            "mode": "non_stream",
            "status_code": status_code,
            "error": "server returned a non-object JSON payload",
        }

    output_text = decoded.get("output_text")
    valid = (
        decoded.get("object") == "response"
        and decoded.get("status") == "completed"
        and isinstance(output_text, str)
        and output_text.strip()
    )
    return {
        "ok": valid,
        "exit_code": 0 if valid else 2,
        "mode": "non_stream",
        "status_code": status_code,
        "response": decoded,
        "output_text": output_text if isinstance(output_text, str) else "",
    }


def stream_responses_request(
    base_url: str,
    api_key: str,
    payload: dict[str, object],
    *,
    timeout: float,
) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url.rstrip('/')}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(request_object, timeout=timeout) as response:
            events = list(read_sse_events(response))
            status_code = response.status
    except error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"responses stream failed with status {exc.code}: {detail.strip() or exc.reason}") from exc
        finally:
            exc.close()
    except error.URLError as exc:
        raise RuntimeError(f"failed to reach {request_object.full_url}: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"responses stream failed for {request_object.full_url}: {exc}") from exc

    if not events:
        return {
            "ok": False,
            "exit_code": 2,
            "mode": "stream",
            "status_code": status_code,
            "error": "stream did not produce any SSE events",
            "events": [],
        }

    event_types = [event.get("type") for event in events if isinstance(event, dict)]
    completed_event = events[-1] if isinstance(events[-1], dict) else {}
    response_payload = completed_event.get("response") if isinstance(completed_event, dict) else None
    output_text = response_payload.get("output_text") if isinstance(response_payload, dict) else None
    valid = (
        "response.created" in event_types
        and "response.output_text.done" in event_types
        and event_types[-1] == "response.completed"
        and isinstance(output_text, str)
        and output_text.strip()
    )
    return {
        "ok": valid,
        "exit_code": 0 if valid else 2,
        "mode": "stream",
        "status_code": status_code,
        "events": events,
        "event_types": event_types,
        "output_text": output_text if isinstance(output_text, str) else "",
    }


def read_sse_events(response: object) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    chunks: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            event = parse_sse_event(chunks)
            if event is not None:
                events.append(event)
            chunks = []
            continue
        chunks.append(line)
    if chunks:
        event = parse_sse_event(chunks)
        if event is not None:
            events.append(event)
    return events


def parse_sse_event(lines: list[str]) -> dict[str, object] | None:
    data_lines = [line[len("data:") :].lstrip() for line in lines if line.startswith("data:")]
    if not data_lines:
        return None
    data = "\n".join(data_lines)
    if data == "[DONE]":
        return {"type": "done"}
    try:
        decoded = json.loads(data)
    except json.JSONDecodeError:
        return {"type": "invalid", "raw": data}
    return decoded if isinstance(decoded, dict) else {"type": "invalid", "payload": decoded}


def render_text(result: dict[str, object]) -> None:
    print(f"mode: {result.get('mode')}")
    print(f"ok: {'yes' if result.get('ok') else 'no'}")
    print(f"status_code: {result.get('status_code')}")
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text:
        print(f"output_text: {output_text}")
    event_types = result.get("event_types")
    if isinstance(event_types, list):
        print(f"event_types: {', '.join(str(event) for event in event_types)}")
    error_message = result.get("error")
    if isinstance(error_message, str) and error_message:
        print(f"error: {error_message}")


def resolve_api_key(api_key_env: str) -> str:
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"api key environment variable '{api_key_env}' is not set or empty")
    return api_key


if __name__ == "__main__":
    raise SystemExit(main())
