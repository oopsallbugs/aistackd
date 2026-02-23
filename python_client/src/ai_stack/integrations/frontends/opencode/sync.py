"""OpenCode global config sync helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from ai_stack.integrations.core import AdapterValidationError
from ai_stack.integrations.shared import load_shared_agents, load_shared_tools

from ai_stack.integrations.adapters.opencode import OpenCodeAdapter


@dataclass(frozen=True)
class OpenCodeSyncResult:
    """Result for an opencode config sync operation."""

    path: Path
    written: bool
    warnings: List[str]
    validation_ok: bool
    validation_messages: List[str]
    payload: Dict[str, Any]


def _default_global_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "opencode.json"


def _load_existing_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Existing opencode config is invalid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Existing opencode config must be a JSON object: {path}")

    return payload


def _render_tool_payload(spec) -> Dict[str, Any]:
    payload = dict(spec.config)
    payload.setdefault("name", spec.name)
    return payload


def _render_agent_payload(spec) -> Dict[str, Any]:
    payload = dict(spec.config)
    payload.setdefault("name", spec.name)
    return payload


def sync_opencode_global_config(
    *,
    context,
    global_path: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    dry_run: bool = False,
) -> OpenCodeSyncResult:
    """Sync global OpenCode config from ai-stack runtime and optional shared assets."""
    target = (global_path or _default_global_config_path()).expanduser()

    adapter = OpenCodeAdapter()
    validation = adapter.validate(context)

    existing = _load_existing_config(target)
    project_payload = adapter.build_project_config(context)

    merged = dict(existing)
    merged.setdefault("$schema", project_payload.get("$schema"))
    merged["provider"] = project_payload["provider"]
    merged["model"] = project_payload["model"]

    warnings: List[str] = list(validation.messages)

    if sync_tools:
        shared_tools = load_shared_tools()
        if not shared_tools:
            warnings.append("No shared tools found; skipping --sync-tools")
        else:
            current_tools = merged.get("tools")
            if not isinstance(current_tools, dict):
                current_tools = {}
            tools_out = dict(current_tools)
            for key, spec in shared_tools.items():
                if key not in tools_out:
                    tools_out[key] = _render_tool_payload(spec)
            merged["tools"] = tools_out

    if sync_agents:
        shared_agents = load_shared_agents()
        if not shared_agents:
            warnings.append("No shared agents found; skipping --sync-agents")
        else:
            current_agents = merged.get("agent")
            if not isinstance(current_agents, dict):
                current_agents = {}
            agents_out = dict(current_agents)
            for key, spec in shared_agents.items():
                if key not in agents_out:
                    agents_out[key] = _render_agent_payload(spec)
            merged["agent"] = agents_out

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    return OpenCodeSyncResult(
        path=target,
        written=not dry_run,
        warnings=warnings,
        validation_ok=validation.ok,
        validation_messages=list(validation.messages),
        payload=merged,
    )


def sync_opencode_global_config_with_defaults(
    *,
    build_context,
    global_path: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    dry_run: bool = False,
) -> OpenCodeSyncResult:
    """Resolve runtime context via callback and sync global OpenCode config."""
    if not callable(build_context):
        raise AdapterValidationError("build_context callback is required")

    context = build_context()
    return sync_opencode_global_config(
        context=context,
        global_path=global_path,
        sync_tools=sync_tools,
        sync_agents=sync_agents,
        dry_run=dry_run,
    )


__all__ = [
    "OpenCodeSyncResult",
    "sync_opencode_global_config",
    "sync_opencode_global_config_with_defaults",
]
