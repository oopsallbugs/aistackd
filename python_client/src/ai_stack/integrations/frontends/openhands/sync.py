"""OpenHands global config sync helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from ai_stack.integrations.adapters.openhands import OpenHandsAdapter
from ai_stack.integrations.core import AdapterValidationError
from ai_stack.integrations.shared import load_shared_agents, load_shared_skills, load_shared_tools


@dataclass(frozen=True)
class OpenHandsSyncResult:
    """Result for an OpenHands config sync operation."""

    config_path: Path
    mcp_json_path: Path | None
    skills_dir: Path
    written: bool
    warnings: List[str]
    validation_ok: bool
    validation_messages: List[str]
    config_payload: Dict[str, Any]
    mcp_payload: Dict[str, Any] | None
    skills_written: List[Path]


def _default_global_config_path() -> Path:
    return Path.home() / ".openhands" / "config.toml"


def _default_mcp_json_path() -> Path:
    return Path.home() / ".openhands" / "mcp.json"


def _default_skills_dir() -> Path:
    return Path.home() / ".openhands" / "skills"


def _quote_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_toml_payload(*, runtime: Dict[str, Any], tools_payload: Dict[str, Any], agents_payload: Dict[str, Any]) -> str:
    lines = [
        "[llm]",
        f'provider = "{_quote_toml(str(runtime["provider"]))}"',
        f'base_url = "{_quote_toml(str(runtime["api_base"]))}"',
        f'model = "{_quote_toml(str(runtime["model"]))}"',
        "",
        "[workspace]",
        f'root = "{_quote_toml(str(runtime["workspace_root"]))}"',
    ]

    if tools_payload:
        lines.extend(["", "[mcp]"])
        for key, spec in tools_payload.items():
            lines.append(f'[mcp.servers."{_quote_toml(key)}"]')
            for cfg_key, cfg_val in spec.items():
                if isinstance(cfg_val, bool):
                    rendered = "true" if cfg_val else "false"
                elif isinstance(cfg_val, int):
                    rendered = str(cfg_val)
                else:
                    rendered = f'"{_quote_toml(str(cfg_val))}"'
                lines.append(f"{cfg_key} = {rendered}")

    if agents_payload:
        lines.extend(["", "[agents]"])
        for key, spec in agents_payload.items():
            lines.append(f'[agents.definitions."{_quote_toml(key)}"]')
            for cfg_key, cfg_val in spec.items():
                rendered = f'"{_quote_toml(str(cfg_val))}"'
                lines.append(f"{cfg_key} = {rendered}")

    return "\n".join(lines).rstrip() + "\n"


def _load_existing_mcp_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Existing OpenHands MCP JSON is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Existing OpenHands MCP JSON must be an object: {path}")
    return payload


def _skill_file_name(skill_key: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in skill_key).strip("-")
    return f"{safe or 'skill'}.md"


def sync_openhands_global_config(
    *,
    context,
    global_path: Path | None = None,
    mcp_json_path: Path | None = None,
    skills_dir: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    sync_skills: bool = False,
    emit_mcp_json: bool = False,
    dry_run: bool = False,
) -> OpenHandsSyncResult:
    """Sync global OpenHands config from ai-stack runtime and optional shared catalogs."""
    target_config = (global_path or _default_global_config_path()).expanduser()
    target_mcp_json = ((mcp_json_path or _default_mcp_json_path()).expanduser() if emit_mcp_json else None)
    target_skills_dir = (skills_dir or _default_skills_dir()).expanduser()

    adapter = OpenHandsAdapter()
    validation = adapter.validate(context)
    runtime_values = adapter.build_runtime_config(context).values
    warnings: List[str] = list(validation.messages)

    tools_payload: Dict[str, Dict[str, Any]] = {}
    if sync_tools:
        shared_tools = load_shared_tools()
        if not shared_tools:
            warnings.append("No shared tools found; skipping --sync-tools")
        else:
            for key, spec in shared_tools.items():
                out = dict(spec.config)
                out.setdefault("name", spec.name)
                tools_payload[key] = out

    agents_payload: Dict[str, Dict[str, Any]] = {}
    if sync_agents:
        shared_agents = load_shared_agents()
        if not shared_agents:
            warnings.append("No shared agents found; skipping --sync-agents")
        else:
            for key, spec in shared_agents.items():
                out = dict(spec.config)
                out.setdefault("name", spec.name)
                agents_payload[key] = out

    skills_payload: Dict[str, Dict[str, Any]] = {}
    if sync_skills:
        shared_skills = load_shared_skills()
        if not shared_skills:
            warnings.append("No shared skills found; skipping --sync-skills")
        else:
            for key, spec in shared_skills.items():
                out = dict(spec.config)
                out["name"] = spec.name
                out["description"] = spec.description
                out["content"] = spec.content
                skills_payload[key] = out

    toml_text = _build_toml_payload(
        runtime=runtime_values,
        tools_payload=tools_payload,
        agents_payload=agents_payload,
    )

    mcp_payload = None
    if emit_mcp_json:
        existing_mcp = _load_existing_mcp_json(target_mcp_json)
        merged_mcp = dict(existing_mcp)
        servers = merged_mcp.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
        out_servers = dict(servers)
        for key, spec in tools_payload.items():
            if key not in out_servers:
                out_servers[key] = dict(spec)
        merged_mcp["mcpServers"] = out_servers
        mcp_payload = merged_mcp

    skill_paths: List[Path] = []
    if sync_skills:
        for skill_key in skills_payload:
            skill_paths.append(target_skills_dir / _skill_file_name(skill_key))

    if not dry_run:
        target_config.parent.mkdir(parents=True, exist_ok=True)
        target_config.write_text(toml_text, encoding="utf-8")

        if emit_mcp_json and target_mcp_json is not None and mcp_payload is not None:
            target_mcp_json.parent.mkdir(parents=True, exist_ok=True)
            target_mcp_json.write_text(json.dumps(mcp_payload, indent=2) + "\n", encoding="utf-8")

        if sync_skills:
            target_skills_dir.mkdir(parents=True, exist_ok=True)
            for skill_key, skill_data in skills_payload.items():
                path = target_skills_dir / _skill_file_name(skill_key)
                body = (
                    f"# {skill_data['name']}\n\n"
                    f"{skill_data['description']}\n\n"
                    f"{skill_data['content']}\n"
                )
                path.write_text(body, encoding="utf-8")

    return OpenHandsSyncResult(
        config_path=target_config,
        mcp_json_path=target_mcp_json,
        skills_dir=target_skills_dir,
        written=not dry_run,
        warnings=warnings,
        validation_ok=validation.ok,
        validation_messages=list(validation.messages),
        config_payload={
            "runtime": runtime_values,
            "tools": tools_payload,
            "agents": agents_payload,
            "skills": skills_payload,
            "toml": toml_text,
        },
        mcp_payload=mcp_payload,
        skills_written=skill_paths,
    )


def sync_openhands_global_config_with_defaults(
    *,
    build_context,
    global_path: Path | None = None,
    mcp_json_path: Path | None = None,
    skills_dir: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    sync_skills: bool = False,
    emit_mcp_json: bool = False,
    dry_run: bool = False,
) -> OpenHandsSyncResult:
    """Resolve runtime context via callback and sync global OpenHands config."""
    if not callable(build_context):
        raise AdapterValidationError("build_context callback is required")
    context = build_context()
    return sync_openhands_global_config(
        context=context,
        global_path=global_path,
        mcp_json_path=mcp_json_path,
        skills_dir=skills_dir,
        sync_tools=sync_tools,
        sync_agents=sync_agents,
        sync_skills=sync_skills,
        emit_mcp_json=emit_mcp_json,
        dry_run=dry_run,
    )


__all__ = [
    "OpenHandsSyncResult",
    "sync_openhands_global_config",
    "sync_openhands_global_config_with_defaults",
]
