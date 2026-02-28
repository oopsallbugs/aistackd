from __future__ import annotations

from pathlib import Path

import pytest

from ai_stack.integrations.frontends.opencode import skills_catalog


def _write_skill(path: Path, *, name: str, description: str, body: str = "Body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_load_opencode_sync_skills_reads_expected_repo_catalog() -> None:
    skills = skills_catalog.load_opencode_sync_skills()

    assert set(skills) == set(skills_catalog.MANAGED_OPENCODE_SKILL_KEYS)
    assert "find-skills" in skills
    assert skills["find-skills"].description


def test_load_opencode_sync_skills_fails_when_managed_skill_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skills_root = tmp_path / "skills"
    for key in skills_catalog.MANAGED_OPENCODE_SKILL_KEYS:
        if key == "find-skills":
            continue
        _write_skill(
            skills_root / key / "SKILL.md",
            name=key,
            description=f"{key} description",
        )

    monkeypatch.setattr(skills_catalog, "_managed_skills_root", lambda: skills_root)

    with pytest.raises(ValueError, match="Managed OpenCode skill file is missing"):
        skills_catalog.load_opencode_sync_skills()


def test_load_opencode_sync_skills_fails_on_malformed_frontmatter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skills_root = tmp_path / "skills"
    for key in skills_catalog.MANAGED_OPENCODE_SKILL_KEYS:
        if key == "find-skills":
            (skills_root / key).mkdir(parents=True, exist_ok=True)
            (skills_root / key / "SKILL.md").write_text(
                "---\n"
                f"name: {key}\n"
                "---\n\n"
                "missing description\n",
                encoding="utf-8",
            )
            continue

        _write_skill(
            skills_root / key / "SKILL.md",
            name=key,
            description=f"{key} description",
        )

    monkeypatch.setattr(skills_catalog, "_managed_skills_root", lambda: skills_root)

    with pytest.raises(ValueError, match="frontmatter field 'description' is required"):
        skills_catalog.load_opencode_sync_skills()
