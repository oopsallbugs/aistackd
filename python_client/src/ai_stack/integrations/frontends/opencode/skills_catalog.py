"""Managed repo-backed skills catalog for OpenCode global sync."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from ai_stack.core.config import config
from ai_stack.integrations.shared.types import SharedSkillSpec

MANAGED_OPENCODE_SKILL_KEYS: Tuple[str, ...] = (
    "ai-stack-runtime-setup",
    "ai-stack-model-operations",
    "ai-stack-opencode-sync",
    "find-skills",
)


def _managed_skills_root() -> Path:
    return config.paths.project_root / "skills"


def _split_frontmatter(raw_text: str, *, path: Path) -> tuple[dict[str, str], str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Skill file missing frontmatter start delimiter: {path}")

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx is None:
        raise ValueError(f"Skill file missing frontmatter end delimiter: {path}")

    fields: dict[str, str] = {}
    for raw in lines[1:end_idx]:
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")

    body = "\n".join(lines[end_idx + 1 :]).strip()
    return fields, body


def _load_managed_skill(key: str, *, root: Path) -> SharedSkillSpec:
    skill_path = root / key / "SKILL.md"
    if not skill_path.exists():
        raise ValueError(f"Managed OpenCode skill file is missing: {skill_path}")

    fields, body = _split_frontmatter(skill_path.read_text(encoding="utf-8"), path=skill_path)

    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    if not name:
        raise ValueError(f"Skill frontmatter field 'name' is required: {skill_path}")
    if not description:
        raise ValueError(f"Skill frontmatter field 'description' is required: {skill_path}")

    return SharedSkillSpec(
        key=key,
        name=name,
        description=description,
        content=body,
    )


def load_opencode_sync_skills() -> Dict[str, SharedSkillSpec]:
    """Return managed OpenCode sync skills from repo root skills catalog."""
    root = _managed_skills_root()
    return {key: _load_managed_skill(key, root=root) for key in MANAGED_OPENCODE_SKILL_KEYS}


__all__ = ["MANAGED_OPENCODE_SKILL_KEYS", "load_opencode_sync_skills"]
