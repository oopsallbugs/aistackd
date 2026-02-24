from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"
EXPECTED_SKILLS = {
    "ai-stack-runtime-setup",
    "ai-stack-model-operations",
    "ai-stack-opencode-sync",
}


def _parse_required_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter start delimiter")

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("missing frontmatter end delimiter")

    fields: dict[str, str] = {}
    for raw in lines[1:end_idx]:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        fields[key] = value

    for required in ("name", "description"):
        if required not in fields:
            raise ValueError(f"missing required frontmatter field: {required}")
        if not fields[required].strip():
            raise ValueError(f"frontmatter field is empty: {required}")
    return fields


def test_expected_skill_files_exist() -> None:
    assert SKILLS_ROOT.exists(), "skills/ directory must exist at repo root"
    actual = {path.name for path in SKILLS_ROOT.iterdir() if path.is_dir()}
    assert EXPECTED_SKILLS.issubset(actual)

    for skill_name in EXPECTED_SKILLS:
        assert (SKILLS_ROOT / skill_name / "SKILL.md").exists()


def test_skill_frontmatter_has_required_fields() -> None:
    for skill_dir in SKILLS_ROOT.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists(), f"missing SKILL.md in {skill_dir.name}"
        fields = _parse_required_frontmatter(skill_md.read_text(encoding="utf-8"))
        assert fields["name"] == skill_dir.name


def test_parse_frontmatter_missing_frontmatter_fails() -> None:
    with pytest.raises(ValueError, match="missing frontmatter start delimiter"):
        _parse_required_frontmatter("# no frontmatter\ncontent")


def test_parse_frontmatter_missing_required_field_fails() -> None:
    text = """---
name: demo-skill
---
# Demo
"""
    with pytest.raises(ValueError, match="missing required frontmatter field: description"):
        _parse_required_frontmatter(text)


def test_parse_frontmatter_empty_description_fails() -> None:
    text = """---
name: demo-skill
description:
---
# Demo
"""
    with pytest.raises(ValueError, match="frontmatter field is empty: description"):
        _parse_required_frontmatter(text)
