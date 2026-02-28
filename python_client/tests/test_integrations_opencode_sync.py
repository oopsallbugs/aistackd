from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_stack.integrations.core.types import IntegrationContext
from ai_stack.integrations.frontends.opencode import sync as opencode_sync
from ai_stack.integrations.shared.types import SharedAgentSpec, SharedSkillSpec, SharedToolSpec


class _FakeClient:
    def __init__(self, *, models=None, n_ctx=32768):
        self._models = models or []
        self._n_ctx = n_ctx

    def health_check(self):
        return True

    def get_models(self):
        return list(self._models)

    def get_model_info(self):
        return {"n_ctx": self._n_ctx}


def _context(tmp_path: Path) -> IntegrationContext:
    return IntegrationContext(
        project_root=tmp_path,
        llama_api_url="http://127.0.0.1:8080",
        default_model="model-a.gguf",
        create_client=lambda **kwargs: _FakeClient(models=["model-a.gguf", "model-b.gguf"]),
    )


def test_sync_global_merges_provider_model_and_preserves_unknown_keys(tmp_path: Path) -> None:
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps({"instructions": ["docs/*.md"], "provider": {"old": {}}, "model": "old/x"}),
        encoding="utf-8",
    )

    result = opencode_sync.sync_opencode_global_config(
        context=_context(tmp_path),
        global_path=target,
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert result.written is True
    assert payload["instructions"] == ["docs/*.md"]
    assert "llama.cpp" in payload["provider"]
    assert payload["model"].startswith("llama.cpp/")


def test_sync_global_merges_shared_tools_and_agents_without_overwriting_existing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps(
            {
                "tools": {
                    "existing": {"name": "existing"},
                    "shared-tool": {"name": "project override"},
                },
                "agent": {
                    "shared-agent": {"name": "project agent override"},
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        opencode_sync,
        "load_shared_tools",
        lambda: {
            "shared-tool": SharedToolSpec(
                key="shared-tool",
                name="shared tool",
                config={"name": "shared tool"},
            ),
            "new-tool": SharedToolSpec(
                key="new-tool",
                name="new tool",
                config={"name": "new tool"},
            ),
        },
    )
    monkeypatch.setattr(
        opencode_sync,
        "load_shared_agents",
        lambda: {
            "shared-agent": SharedAgentSpec(
                key="shared-agent",
                name="shared agent",
                config={"name": "shared agent"},
            ),
            "new-agent": SharedAgentSpec(
                key="new-agent",
                name="new agent",
                config={"name": "new agent"},
            ),
        },
    )
    opencode_sync.sync_opencode_global_config(
        context=_context(tmp_path),
        global_path=target,
        sync_tools=True,
        sync_agents=True,
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["tools"]["shared-tool"]["name"] == "project override"
    assert payload["tools"]["new-tool"]["name"] == "new tool"
    assert payload["agent"]["shared-agent"]["name"] == "project agent override"
    assert payload["agent"]["new-agent"]["name"] == "new agent"


def test_sync_global_writes_skills_to_global_skills_dir(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "opencode.json"
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(
        opencode_sync,
        "load_opencode_sync_skills",
        lambda: {
            "shared-skill": SharedSkillSpec(
                key="shared-skill",
                name="shared skill",
                description="shared desc",
                content="shared content",
            ),
        },
    )

    result = opencode_sync.sync_opencode_global_config(
        context=_context(tmp_path),
        global_path=target,
        skills_dir=skills_dir,
        sync_skills=True,
    )

    skill_path = skills_dir / "shared-skill" / "SKILL.md"
    assert result.skills_dir == skills_dir
    assert skill_path in result.skills_written
    assert skill_path.exists()
    text = skill_path.read_text(encoding="utf-8")
    assert "name: shared skill" in text
    assert "description: shared desc" in text
    assert "shared content" in text


def test_sync_global_writes_managed_repo_skills_including_find_skills(tmp_path: Path) -> None:
    target = tmp_path / "opencode.json"
    skills_dir = tmp_path / "skills"

    result = opencode_sync.sync_opencode_global_config(
        context=_context(tmp_path),
        global_path=target,
        skills_dir=skills_dir,
        sync_skills=True,
    )

    written_dirs = {path.parent.name for path in result.skills_written}
    assert written_dirs == {
        "ai-stack-runtime-setup",
        "ai-stack-model-operations",
        "ai-stack-opencode-sync",
        "find-skills",
    }
    assert (skills_dir / "find-skills" / "SKILL.md").exists()


def test_sync_global_skills_sync_preserves_unrelated_existing_skill_dir(tmp_path: Path) -> None:
    target = tmp_path / "opencode.json"
    skills_dir = tmp_path / "skills"
    unmanaged = skills_dir / "user-custom-skill" / "SKILL.md"
    unmanaged.parent.mkdir(parents=True, exist_ok=True)
    unmanaged.write_text("user content\n", encoding="utf-8")

    opencode_sync.sync_opencode_global_config(
        context=_context(tmp_path),
        global_path=target,
        skills_dir=skills_dir,
        sync_skills=True,
    )

    assert unmanaged.exists()
    assert unmanaged.read_text(encoding="utf-8") == "user content\n"


def test_sync_global_dry_run_does_not_write(tmp_path: Path) -> None:
    target = tmp_path / "opencode.json"

    result = opencode_sync.sync_opencode_global_config(
        context=_context(tmp_path),
        global_path=target,
        dry_run=True,
    )

    assert result.written is False
    assert target.exists() is False


def test_sync_global_invalid_existing_json_raises_value_error(tmp_path: Path) -> None:
    target = tmp_path / "opencode.json"
    target.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON"):
        opencode_sync.sync_opencode_global_config(
            context=_context(tmp_path),
            global_path=target,
        )
