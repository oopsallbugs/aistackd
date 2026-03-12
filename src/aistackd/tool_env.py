"""Subprocess environment helpers for operator tools."""

from __future__ import annotations

import json
import os
from pathlib import Path


def build_operator_tool_env(project_root: Path | None) -> dict[str, str]:
    """Return a subprocess environment with managed backend bin paths prepended."""
    environment = os.environ.copy()
    managed_bin_dir = resolve_managed_llama_cpp_bin_dir(project_root)
    if managed_bin_dir is None:
        return environment

    current_path = environment.get("PATH", "")
    path_parts = [str(managed_bin_dir)]
    if current_path:
        path_parts.append(current_path)
    environment["PATH"] = os.pathsep.join(path_parts)
    return environment


def resolve_managed_llama_cpp_bin_dir(project_root: Path | None) -> Path | None:
    """Return the managed llama.cpp bin directory for one project, if available."""
    if project_root is None:
        return None

    installation_path = project_root.resolve() / ".aistackd" / "host" / "backend_installation.json"
    try:
        payload = json.loads(installation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    candidates: list[Path] = []
    server_binary = payload.get("server_binary")
    if isinstance(server_binary, str) and server_binary.strip():
        candidates.append(Path(server_binary).expanduser().parent)
    cli_binary = payload.get("cli_binary")
    if isinstance(cli_binary, str) and cli_binary.strip():
        candidates.append(Path(cli_binary).expanduser().parent)
    backend_root = payload.get("backend_root")
    if isinstance(backend_root, str) and backend_root.strip():
        candidates.append(Path(backend_root).expanduser() / "bin")

    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            return resolved
    return None
