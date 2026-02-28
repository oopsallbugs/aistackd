from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_stack.integrations.core.types import IntegrationContext
from ai_stack.integrations.frontends.openhands import sync as openhands_sync
from ai_stack.integrations.shared.types import SharedAgentSpec, SharedSkillSpec, SharedToolSpec


class _FakeClient:
    def health_check(self):
        return True

    def chat(self, messages, **kwargs):
        _ = (messages, kwargs)
        class _Resp:
            content = "ok"
        return _Resp()


def _context(tmp_path: Path) -> IntegrationContext:
    return IntegrationContext(
        project_root=tmp_path,
        llama_api_url="http://127.0.0.1:8080",
        default_model="model-a.gguf",
        create_client=lambda **kwargs: _FakeClient(),
    )


def test_sync_openhands_dry_run_no_files(tmp_path: Path) -> None:
    result = openhands_sync.sync_openhands_global_config(
        context=_context(tmp_path),
        global_path=tmp_path / "config.toml",
        mcp_json_path=tmp_path / "mcp.json",
        skills_dir=tmp_path / "skills",
        sync_tools=True,
        sync_agents=True,
        sync_skills=True,
        emit_mcp_json=True,
        dry_run=True,
    )
    assert result.written is False
    assert not (tmp_path / "config.toml").exists()


def test_sync_openhands_writes_toml_json_and_skills(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        openhands_sync,
        "load_shared_tools",
        lambda: {
            "tool-a": SharedToolSpec(key="tool-a", name="Tool A", config={"command": "echo"}),
        },
    )
    monkeypatch.setattr(
        openhands_sync,
        "load_shared_agents",
        lambda: {
            "agent-a": SharedAgentSpec(key="agent-a", name="Agent A", config={"mode": "balanced"}),
        },
    )
    monkeypatch.setattr(
        openhands_sync,
        "load_shared_skills",
        lambda: {
            "skill-a": SharedSkillSpec(
                key="skill-a",
                name="Skill A",
                description="demo",
                content="Do steps",
            ),
        },
    )

    config_path = tmp_path / "config.toml"
    mcp_path = tmp_path / "mcp.json"
    skills_dir = tmp_path / "skills"
    result = openhands_sync.sync_openhands_global_config(
        context=_context(tmp_path),
        global_path=config_path,
        mcp_json_path=mcp_path,
        skills_dir=skills_dir,
        sync_tools=True,
        sync_agents=True,
        sync_skills=True,
        emit_mcp_json=True,
    )

    assert result.written is True
    assert config_path.exists()
    assert mcp_path.exists()
    assert any(path.exists() for path in result.skills_written)
    assert "[llm]" in config_path.read_text(encoding="utf-8")
    payload = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "tool-a" in payload["mcpServers"]


def test_sync_openhands_invalid_existing_mcp_json_raises(tmp_path: Path) -> None:
    bad_mcp = tmp_path / "mcp.json"
    bad_mcp.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid"):
        openhands_sync.sync_openhands_global_config(
            context=_context(tmp_path),
            global_path=tmp_path / "config.toml",
            mcp_json_path=bad_mcp,
            emit_mcp_json=True,
        )
