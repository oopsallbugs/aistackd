#!/usr/bin/env python3
"""Wait for the configured aistackd runtime to become usable."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib import error, request

DEFAULT_BASE_URL = "${base_url}"
DEFAULT_API_KEY_ENV = "${api_key_env}"
DEFAULT_PROMPT = "say hello"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait until the configured aistackd runtime satisfies one readiness condition.",
    )
    parser.add_argument(
        "condition",
        nargs="?",
        choices=("health", "ready", "responses"),
        default="ready",
        help="condition to wait for (default: ready)",
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
    parser.add_argument("--timeout", type=float, default=30.0, help="overall timeout in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="poll interval in seconds")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help=f"smoke prompt for responses mode (default: {DEFAULT_PROMPT!r})")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="output format")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        api_key = resolve_api_key(args.api_key_env)
        result = wait_for_runtime(
            args.base_url,
            api_key,
            args.condition,
            timeout=args.timeout,
            interval=args.interval,
            prompt=args.prompt,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        render_text(result)
    return int(result["exit_code"])


def wait_for_runtime(
    base_url: str,
    api_key: str,
    condition: str,
    *,
    timeout: float,
    interval: float,
    prompt: str,
) -> dict[str, object]:
    if timeout <= 0:
        raise RuntimeError("--timeout must be positive")
    if interval <= 0:
        raise RuntimeError("--interval must be positive")

    started_at = time.monotonic()
    attempts = 0
    last_probe: dict[str, object] = {}

    while True:
        attempts += 1
        elapsed = time.monotonic() - started_at
        if condition == "health":
            probe = probe_health(base_url, api_key)
            if probe["ok"]:
                return _success_result(condition, attempts, elapsed, probe)
            last_probe = probe
        elif condition == "ready":
            probe = probe_ready(base_url, api_key)
            if probe["ok"]:
                return _success_result(condition, attempts, elapsed, probe)
            last_probe = probe
        else:
            probe = probe_responses(base_url, api_key, prompt)
            if probe["ok"]:
                return _success_result(condition, attempts, elapsed, probe)
            last_probe = probe

        if elapsed >= timeout:
            return {
                "ok": False,
                "exit_code": 1,
                "condition": condition,
                "attempts": attempts,
                "elapsed_seconds": round(elapsed, 3),
                "last_probe": last_probe,
            }
        time.sleep(interval)


def probe_health(base_url: str, api_key: str) -> dict[str, object]:
    result = request_json(base_url, "/health", api_key)
    payload = result["payload"]
    ok = result["status_code"] == 200 and isinstance(payload, dict) and payload.get("status") == "ok"
    return {"kind": "health", "ok": ok, **result}


def probe_ready(base_url: str, api_key: str) -> dict[str, object]:
    result = request_json(base_url, "/health", api_key)
    payload = result["payload"]
    ok = (
        result["status_code"] == 200
        and isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("backend_process_status") == "running"
        and isinstance(payload.get("active_model"), str)
        and bool(payload.get("active_model"))
    )
    return {"kind": "ready", "ok": ok, **result}


def probe_responses(base_url: str, api_key: str, prompt: str) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url.rstrip('/')}/v1/responses",
        data=json.dumps({"input": prompt, "stream": False}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
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
        return {"kind": "responses", "ok": False, "status_code": 0, "payload": {"error": str(exc.reason)}}
    except OSError as exc:
        return {"kind": "responses", "ok": False, "status_code": 0, "payload": {"error": str(exc)}}

    try:
        decoded = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        decoded = {"raw_body": body}
    if not isinstance(decoded, dict):
        decoded = {"payload": decoded}

    ok = status_code == 200 and decoded.get("status") == "completed" and isinstance(decoded.get("output_text"), str)
    return {"kind": "responses", "ok": ok, "status_code": status_code, "payload": decoded}


def request_json(base_url: str, path: str, api_key: str) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with request.urlopen(request_object, timeout=5) as response:
            body = response.read().decode("utf-8")
            status_code = response.status
    except error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            status_code = exc.code
        finally:
            exc.close()
    except error.URLError as exc:
        return {"status_code": 0, "payload": {"error": str(exc.reason)}}
    except OSError as exc:
        return {"status_code": 0, "payload": {"error": str(exc)}}

    try:
        decoded = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        decoded = {"raw_body": body}
    if not isinstance(decoded, dict):
        decoded = {"payload": decoded}
    return {"status_code": status_code, "payload": decoded}


def _success_result(condition: str, attempts: int, elapsed: float, probe: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "exit_code": 0,
        "condition": condition,
        "attempts": attempts,
        "elapsed_seconds": round(elapsed, 3),
        "last_probe": probe,
    }


def render_text(result: dict[str, object]) -> None:
    print(f"condition: {result.get('condition')}")
    print(f"ok: {'yes' if result.get('ok') else 'no'}")
    print(f"attempts: {result.get('attempts')}")
    print(f"elapsed_seconds: {result.get('elapsed_seconds')}")
    last_probe = result.get("last_probe")
    if isinstance(last_probe, dict):
        print(f"probe_kind: {last_probe.get('kind')}")
        print(f"status_code: {last_probe.get('status_code')}")
        payload = last_probe.get("payload")
        if isinstance(payload, dict):
            if "status" in payload:
                print(f"status: {payload.get('status')}")
            if "active_model" in payload:
                print(f"active_model: {payload.get('active_model') or 'none'}")
            if "backend_process_status" in payload:
                print(f"backend_process_status: {payload.get('backend_process_status')}")
            if "output_text" in payload:
                print(f"output_text: {payload.get('output_text')}")
            if "error" in payload:
                print(f"error: {payload.get('error')}")


def resolve_api_key(api_key_env: str) -> str:
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"api key environment variable '{api_key_env}' is not set or empty")
    return api_key


if __name__ == "__main__":
    raise SystemExit(main())
