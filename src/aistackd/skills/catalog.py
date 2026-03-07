"""Shared content catalog constants and helpers."""

from __future__ import annotations

from pathlib import Path
from string import Template

SHARED_SKILLS_DIRECTORY_NAME = "skills"
SHARED_TOOLS_DIRECTORY_NAME = "tools"
BASELINE_SKILLS = ("find-skills",)
BASELINE_TOOLS = ("runtime-status", "model-admin")
PLANNED_BASELINE_SKILLS = BASELINE_SKILLS
PLANNED_BASELINE_TOOLS = BASELINE_TOOLS
SKILL_FILE_NAME = "SKILL.md"
TOOL_FILE_SUFFIX = ".py"


def shared_skills_root() -> Path:
    """Return the repo-owned shared skills root."""
    return Path(__file__).resolve().parents[3] / SHARED_SKILLS_DIRECTORY_NAME


def shared_tools_root() -> Path:
    """Return the repo-owned shared tools root."""
    return Path(__file__).resolve().parents[3] / SHARED_TOOLS_DIRECTORY_NAME


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


def baseline_tool_path(tool_name: str) -> Path:
    """Return the tracked source path for a baseline tool template."""
    return shared_tools_root() / f"{tool_name}{TOOL_FILE_SUFFIX}"


def load_baseline_tool_contents(
    tool_names: tuple[str, ...] | list[str],
    *,
    base_url: str,
    responses_base_url: str,
    api_key_env: str,
) -> dict[str, str]:
    """Load and render the requested baseline tool templates."""
    contents: dict[str, str] = {}
    substitutions = {
        "base_url": base_url,
        "responses_base_url": responses_base_url,
        "api_key_env": api_key_env,
    }
    for tool_name in tool_names:
        tool_path = baseline_tool_path(tool_name)
        if not tool_path.exists():
            raise FileNotFoundError(f"baseline tool '{tool_name}' is missing at {tool_path}")
        template = Template(tool_path.read_text(encoding="utf-8"))
        contents[tool_name] = template.safe_substitute(substitutions)
    return contents
