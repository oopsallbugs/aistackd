#!/usr/bin/env python3
"""Inspect the configured aistackd runtime endpoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request

DEFAULT_BASE_URL = "${base_url}"
DEFAULT_RESPONSES_BASE_URL = "${responses_base_url}"
DEFAULT_API_KEY_ENV = "${api_key_env}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the configured aistackd runtime and control-plane health.",
    )
    parser.add_argument(
        "resource",
        nargs="?",
        choices=("all", "runtime", "health", "models"),
        default="all",
        help="endpoint group to inspect",
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
        payload, exit_code = collect_payload(args.base_url, api_key, args.resource)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return exit_code

    render_text(payload, args.resource)
    return exit_code


def collect_payload(base_url: str, api_key: str, resource: str) -> tuple[dict[str, object], int]:
    normalized_base_url = base_url.rstrip("/")
    resources = ("runtime", "health", "models") if resource == "all" else (resource,)
    payload: dict[str, object] = {}
    exit_code = 0

    for item in resources:
        path = endpoint_path(item)
        result = request_json(normalized_base_url, path, api_key)
        payload[item] = {
            "status_code": result["status_code"],
            "payload": result["payload"],
        }
        if result["status_code"] >= 400:
            exit_code = 1

    if resource != "all":
        return payload[resource], exit_code
    return payload, exit_code


def endpoint_path(resource: str) -> str:
    if resource == "runtime":
        return "/admin/runtime"
    if resource == "health":
        return "/health"
    if resource == "models":
        return "/v1/models"
    raise RuntimeError(f"unsupported runtime-status resource '{resource}'")


def request_json(base_url: str, path: str, api_key: str) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url}{path}",
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
        raise RuntimeError(f"failed to reach {base_url}{path}: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"runtime request failed for {base_url}{path}: {exc}") from exc

    try:
        decoded = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        decoded = {"raw_body": body}

    if not isinstance(decoded, dict):
        decoded = {"payload": decoded}

    return {"status_code": status_code, "payload": decoded}


def render_text(payload: dict[str, object], resource: str) -> None:
    if resource == "all":
        print(f"base_url: {DEFAULT_BASE_URL}")
        print(f"responses_base_url: {DEFAULT_RESPONSES_BASE_URL}")
        for item in ("runtime", "health", "models"):
            print("")
            _render_resource_section(item, payload[item])
        return
    _render_resource_section(resource, payload)


def _render_resource_section(resource: str, section: object) -> None:
    if not isinstance(section, dict):
        print(f"{resource}: invalid payload")
        return

    status_code = section.get("status_code")
    body = section.get("payload")
    print(f"{resource}: status_code={status_code}")
    if not isinstance(body, dict):
        print(body)
        return

    if resource == "runtime":
        runtime = body.get("runtime")
        service = body.get("service")
        if isinstance(runtime, dict):
            print(f"  active_model: {runtime.get('active_model') or 'none'}")
            print(f"  backend_status: {runtime.get('backend_status')}")
            print(f"  backend_process_status: {runtime.get('backend_process_status')}")
            installed_models = runtime.get("installed_models")
            if isinstance(installed_models, list):
                print(f"  installed_models: {len(installed_models)}")
        if isinstance(service, dict):
            print(f"  service_base_url: {service.get('base_url')}")
        return

    if resource == "health":
        print(f"  status: {body.get('status')}")
        print(f"  active_model: {body.get('active_model') or 'none'}")
        print(f"  backend_process_status: {body.get('backend_process_status')}")
        return

    if resource == "models":
        print(f"  active_model: {body.get('active_model') or 'none'}")
        data = body.get("data")
        if isinstance(data, list):
            print(f"  installed_models: {len(data)}")
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                active_marker = "*" if entry.get("active") else " "
                print(
                    f"  {active_marker} {entry.get('id')}: "
                    f"source={entry.get('source')} method={entry.get('acquisition_method')} status={entry.get('status')}"
                )
        return

    print(json.dumps(body, indent=2))


def resolve_api_key(api_key_env: str) -> str:
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"api key environment variable '{api_key_env}' is not set or empty")
    return api_key


if __name__ == "__main__":
    raise SystemExit(main())
