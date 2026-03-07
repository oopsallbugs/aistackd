"""Shared content catalog constants and helpers."""

from __future__ import annotations

from pathlib import Path

SHARED_SKILLS_DIRECTORY_NAME = "skills"
SHARED_TOOLS_DIRECTORY_NAME = "tools"
BASELINE_SKILLS = ("find-skills",)
BASELINE_TOOLS: tuple[str, ...] = ()
PLANNED_BASELINE_SKILLS = BASELINE_SKILLS
PLANNED_BASELINE_TOOLS = BASELINE_TOOLS
SKILL_FILE_NAME = "SKILL.md"


def shared_skills_root() -> Path:
    """Return the repo-owned shared skills root."""
    return Path(__file__).resolve().parents[3] / SHARED_SKILLS_DIRECTORY_NAME


def baseline_skill_path(skill_name: str) -> Path:
    """Return the tracked source path for a baseline skill."""
    return shared_skills_root() / skill_name / SKILL_FILE_NAME


def load_baseline_skill_contents(skill_names: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Load the contents of the requested baseline skills."""
    contents: dict[str, str] = {}
    for skill_name in skill_names:
        skill_path = baseline_skill_path(skill_name)
        if not skill_path.exists():
            raise FileNotFoundError(f"baseline skill '{skill_name}' is missing at {skill_path}")
        contents[skill_name] = skill_path.read_text(encoding="utf-8")
    return contents
