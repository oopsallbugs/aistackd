"""OpenCode global config sync helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from ai_stack.integrations.adapters.opencode import OpenCodeAdapter
from ai_stack.integrations.core import AdapterValidationError
from ai_stack.integrations.frontends.opencode.skills_catalog import load_opencode_sync_skills
from ai_stack.integrations.shared import load_shared_agents, load_shared_tools


@dataclass(frozen=True)
class OpenCodeSyncResult:
    """Result for an opencode config sync operation."""

    path: Path
    written: bool
    warnings: List[str]
    validation_ok: bool
    validation_messages: List[str]
    payload: Dict[str, Any]
    skills_dir: Path | None = None
    skills_written: List[Path] = field(default_factory=list)


def _default_global_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "opencode.json"


def _default_skills_dir() -> Path:
    return Path.home() / ".config" / "opencode" / "skills"


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


def _render_skill_file(spec) -> str:
    frontmatter = (
        "---\n"
        f"name: {spec.name}\n"
        f"description: {spec.description}\n"
        "---\n\n"
    )
    body = spec.content.rstrip() + "\n"
    return frontmatter + body


def sync_opencode_global_config(
    *,
    context,
    global_path: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    sync_skills: bool = False,
    skills_dir: Path | None = None,
    dry_run: bool = False,
) -> OpenCodeSyncResult:
    """Sync global OpenCode config from ai-stack runtime and optional shared assets."""
    target = (global_path or _default_global_config_path()).expanduser()
    target_skills_dir = (skills_dir or _default_skills_dir()).expanduser()

    adapter = OpenCodeAdapter()
    validation = adapter.validate(context)

    existing = _load_existing_config(target)
    project_payload = adapter.build_project_config(context)

    merged = dict(existing)
    merged.setdefault("$schema", project_payload.get("$schema"))
    merged["provider"] = project_payload["provider"]
    merged["model"] = project_payload["model"]

    warnings: List[str] = list(validation.messages)
    skills_written: List[Path] = []

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

    if sync_skills:
        shared_skills = load_opencode_sync_skills()
        if not shared_skills:
            warnings.append("No shared skills found; skipping --sync-skills")
        else:
            skills_written = [target_skills_dir / key / "SKILL.md" for key in shared_skills]
            if not dry_run:
                for key, spec in shared_skills.items():
                    skill_path = target_skills_dir / key / "SKILL.md"
                    skill_path.parent.mkdir(parents=True, exist_ok=True)
                    skill_path.write_text(_render_skill_file(spec), encoding="utf-8")

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
        skills_dir=target_skills_dir if sync_skills else None,
        skills_written=skills_written,
    )


def sync_opencode_global_config_with_defaults(
    *,
    build_context,
    global_path: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    sync_skills: bool = False,
    skills_dir: Path | None = None,
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
        sync_skills=sync_skills,
        skills_dir=skills_dir,
        dry_run=dry_run,
    )


__all__ = [
    "OpenCodeSyncResult",
    "sync_opencode_global_config",
    "sync_opencode_global_config_with_defaults",
]
