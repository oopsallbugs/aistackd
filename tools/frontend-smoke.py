#!/usr/bin/env python3
"""Run one frontend-side smoke check against the configured aistackd host."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request

DEFAULT_ACTIVE_PROFILE = "${active_profile}"
DEFAULT_BASE_URL = "${base_url}"
DEFAULT_API_KEY_ENV = "${api_key_env}"
DEFAULT_MODEL = "${model}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate that this frontend machine can reach the configured aistackd host and run one smoke prompt.",
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
        "--prompt",
        default="say hello in one short sentence",
        help="smoke prompt to send to /v1/responses",
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
        payload, exit_code = run_smoke(args.base_url, api_key, args.prompt)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return exit_code

    render_text(payload)
    return exit_code


def run_smoke(base_url: str, api_key: str, prompt: str) -> tuple[dict[str, object], int]:
    normalized_base_url = base_url.rstrip("/")
    health = request_json(normalized_base_url, "/health", api_key, method="GET")
    runtime = request_json(normalized_base_url, "/admin/runtime", api_key, method="GET")
    responses = request_json(
        normalized_base_url,
        "/v1/responses",
        api_key,
        method="POST",
        payload={"input": prompt, "stream": False},
    )

    health_payload = health["payload"] if isinstance(health["payload"], dict) else {}
    runtime_payload = runtime["payload"] if isinstance(runtime["payload"], dict) else {}
    responses_payload = responses["payload"] if isinstance(responses["payload"], dict) else {}
    runtime_state = runtime_payload.get("runtime") if isinstance(runtime_payload.get("runtime"), dict) else {}

    payload: dict[str, object] = {
        "profile": DEFAULT_ACTIVE_PROFILE,
        "base_url": normalized_base_url,
        "health": {
            "status_code": health["status_code"],
            "status": health_payload.get("status"),
            "status_reason": health_payload.get("status_reason"),
            "backend_process_status": health_payload.get("backend_process_status"),
            "ok": health["status_code"] == 200,
        },
        "runtime": {
            "status_code": runtime["status_code"],
            "active_model": runtime_state.get("active_model"),
            "backend_process_status": runtime_state.get("backend_process_status"),
            "ok": runtime["status_code"] == 200,
        },
        "responses": {
            "status_code": responses["status_code"],
            "output_text": responses_payload.get("output_text"),
            "ok": responses["status_code"] == 200,
        },
    }
    payload["ok"] = bool(payload["health"]["ok"] and payload["runtime"]["ok"] and payload["responses"]["ok"])  # type: ignore[index]
    return payload, 0 if payload["ok"] else 1


def request_json(
    base_url: str,
    path: str,
    api_key: str,
    *,
    method: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with request.urlopen(request_object, timeout=15) as response:
            body = response.read().decode("utf-8")
            status_code = response.status
    except error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            status_code = exc.code
        finally:
            exc.close()
    except error.URLError as exc:
        raise RuntimeError(f"failed to reach {base_url}{path}: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"request failed for {base_url}{path}: {exc}") from exc

    try:
        decoded = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        decoded = {"raw_body": body}
    if not isinstance(decoded, dict):
        decoded = {"payload": decoded}
    return {"status_code": status_code, "payload": decoded}


def render_text(payload: dict[str, object]) -> None:
    print("frontend smoke")
    print(f"profile: {payload.get('profile')}")
    print(f"base_url: {payload.get('base_url')}")
    for section_name in ("health", "runtime", "responses"):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        print(
            f"{section_name}: status_code={section.get('status_code')} "
            f"ok={'yes' if section.get('ok') else 'no'}"
        )
        if section_name == "health":
            print(f"  status: {section.get('status')}")
            print(f"  status_reason: {section.get('status_reason')}")
            print(f"  backend_process_status: {section.get('backend_process_status')}")
        elif section_name == "runtime":
            print(f"  active_model: {section.get('active_model') or DEFAULT_MODEL}")
            print(f"  backend_process_status: {section.get('backend_process_status')}")
        else:
            print(f"  output_text: {section.get('output_text') or ''}")
    print(f"overall: {'ok' if payload.get('ok') else 'failed'}")


def resolve_api_key(api_key_env: str) -> str:
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"api key environment variable '{api_key_env}' is not set or empty")
    return api_key


if __name__ == "__main__":
    raise SystemExit(main())
