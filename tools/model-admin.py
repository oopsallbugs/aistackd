#!/usr/bin/env python3
"""Manage models through the configured aistackd control-plane admin API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request

DEFAULT_BASE_URL = "${base_url}"
DEFAULT_API_KEY_ENV = "${api_key_env}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search, recommend, install, and activate models through the aistackd admin API.",
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

    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="search the live llmfit catalog through the host")
    search_parser.add_argument("query", nargs="?", help="optional query string")

    subparsers.add_parser("recommend", help="show llmfit recommendations from the host")
    subparsers.add_parser("installed", help="list installed host models through the control plane")

    install_parser = subparsers.add_parser("install", help="install one model into host state")
    install_parser.add_argument("model", nargs="?", help="model identifier to install")
    install_parser.add_argument("--source", choices=("llmfit", "hugging_face"), help="force one model source")
    install_parser.add_argument("--gguf-path", help="explicit path to a local GGUF to import")
    install_parser.add_argument(
        "--local-root",
        dest="local_roots",
        action="append",
        default=[],
        help="additional local root to scan for matching GGUF files",
    )
    install_parser.add_argument("--hf-url", help="Hugging Face model/file URL to use for fallback acquisition")
    install_parser.add_argument("--hf-repo", help="Hugging Face repo to use for fallback acquisition")
    install_parser.add_argument("--hf-file", help="GGUF filename to use for Hugging Face fallback")
    install_parser.add_argument("--hf-cli", help="Hugging Face CLI executable to use for fallback downloads")
    install_parser.add_argument("--activate", action="store_true", help="activate the model after installing it")

    activate_parser = subparsers.add_parser("activate", help="activate an installed host model")
    activate_parser.add_argument("model", help="installed model identifier to activate")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        api_key = resolve_api_key(args.api_key_env)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        payload, exit_code = dispatch(args, api_key)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return exit_code

    render_text(args.command, payload)
    return exit_code


def dispatch(args: argparse.Namespace, api_key: str) -> tuple[dict[str, object], int]:
    base_url = args.base_url.rstrip("/")
    if args.command == "search":
        return post_json(base_url, "/admin/models/search", api_key, {"query": args.query}), 0
    if args.command == "recommend":
        return post_json(base_url, "/admin/models/recommend", api_key, {}), 0
    if args.command == "installed":
        return get_json(base_url, "/v1/models", api_key), 0
    if args.command == "install":
        payload: dict[str, object] = {"activate": args.activate}
        if args.model is not None:
            payload["model"] = args.model
        for field_name in ("source", "gguf_path", "hf_url", "hf_repo", "hf_file", "hf_cli"):
            value = getattr(args, field_name)
            if value is not None:
                payload[field_name] = value
        if args.local_roots:
            payload["local_roots"] = list(args.local_roots)
        result = post_json(base_url, "/admin/models/install", api_key, payload)
        return result, 0
    if args.command == "activate":
        result = post_json(
            base_url,
            "/admin/models/activate",
            api_key,
            {"model": args.model},
        )
        return result, 0
    raise RuntimeError(f"unsupported command '{args.command}'")


def get_json(base_url: str, path: str, api_key: str) -> dict[str, object]:
    request_object = request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    return perform_json_request(request_object)


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
    return perform_json_request(request_object)


def perform_json_request(request_object: request.Request) -> dict[str, object]:
    try:
        with request.urlopen(request_object, timeout=30) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"request failed with status {exc.code}: {body.strip() or exc.reason}"
            ) from exc
        if isinstance(decoded, dict):
            error_payload = decoded.get("error")
            if isinstance(error_payload, dict):
                message = error_payload.get("message")
                if isinstance(message, str) and message.strip():
                    raise RuntimeError(f"request failed with status {exc.code}: {message.strip()}") from exc
        raise RuntimeError(f"request failed with status {exc.code}: {body.strip() or exc.reason}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"failed to reach {request_object.full_url}: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"request failed for {request_object.full_url}: {exc}") from exc

    try:
        decoded = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"server returned invalid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("server returned a non-object JSON payload")
    return decoded


def render_text(command: str, payload: dict[str, object]) -> None:
    if command in {"search", "recommend"}:
        models = payload.get("models")
        print(f"available_models: {len(models) if isinstance(models, list) else 0}")
        if isinstance(models, list):
            for entry in models:
                if not isinstance(entry, dict):
                    continue
                parts = [
                    str(entry.get("name")),
                    f"source={entry.get('source')}",
                    f"context={entry.get('context_window')}",
                    f"quantization={entry.get('quantization')}",
                ]
                rank = entry.get("recommended_rank")
                if rank is not None:
                    parts.append(f"recommended_rank={rank}")
                parts.append(f"summary={entry.get('summary')}")
                print(" ".join(parts))
        return

    if command == "installed":
        print(f"active_model: {payload.get('active_model') or 'none'}")
        models = payload.get("data")
        print(f"installed_models: {len(models) if isinstance(models, list) else 0}")
        if isinstance(models, list):
            for entry in models:
                if not isinstance(entry, dict):
                    continue
                active_marker = "*" if entry.get("active") else " "
                print(
                    f"{active_marker} {entry.get('id')}: "
                    f"source={entry.get('source')} method={entry.get('acquisition_method')} status={entry.get('status')}"
                )
        return

    if command == "install":
        model = payload.get("model")
        if isinstance(model, dict):
            print(f"{payload.get('action')}: {model.get('model')}")
            print(f"source: {model.get('source')}")
            print(f"acquisition_method: {model.get('acquisition_method')}")
            print(f"artifact_path: {model.get('artifact_path')}")
        print(f"active_model: {payload.get('active_model') or 'none'}")
        acquisition = payload.get("acquisition")
        if isinstance(acquisition, dict):
            attempts = acquisition.get("attempts")
            if isinstance(attempts, list):
                for attempt in attempts:
                    if not isinstance(attempt, dict):
                        continue
                    status = "ok" if attempt.get("ok") else "failed"
                    print(
                        f"attempt: {attempt.get('provider')}/{attempt.get('strategy')} "
                        f"status={status} detail={attempt.get('detail')}"
                    )
        return

    if command == "activate":
        runtime = payload.get("runtime")
        if isinstance(runtime, dict):
            print(f"active_model: {runtime.get('active_model') or 'none'}")
            print(f"active_source: {runtime.get('active_source') or 'none'}")
            print(f"activation_state: {runtime.get('activation_state')}")
        return

    print(json.dumps(payload, indent=2))


def resolve_api_key(api_key_env: str) -> str:
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"api key environment variable '{api_key_env}' is not set or empty")
    return api_key


if __name__ == "__main__":
    raise SystemExit(main())
