from __future__ import annotations

import sys
from pathlib import Path

import ai_stack.cli.integrations as cli_integrations
from ai_stack.integrations.frontends.openhands.sync import OpenHandsSyncResult


def test_openhands_sync_cli_dry_run_prints_payload(monkeypatch, capsys, tmp_path: Path) -> None:
    fake_result = OpenHandsSyncResult(
        config_path=tmp_path / "config.toml",
        mcp_json_path=tmp_path / "mcp.json",
        skills_dir=tmp_path / "skills",
        written=False,
        warnings=["warn"],
        validation_ok=True,
        validation_messages=[],
        config_payload={"runtime": {"model": "m.gguf"}},
        mcp_payload={"mcpServers": {}},
        skills_written=[],
    )
    monkeypatch.setattr(cli_integrations, "sync_openhands_global_config", lambda **kwargs: fake_result)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sync-openhands-config",
            "--dry-run",
            "--print",
            "--sync-tools",
            "--sync-agents",
            "--sync-skills",
            "--emit-mcp-json",
        ],
    )

    rc = cli_integrations.sync_openhands_config_cli()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Dry run complete" in out
    assert "MCP JSON:" in out


def test_openhands_sync_cli_value_error_returns_exit_1(monkeypatch, capsys) -> None:
    def _boom(**kwargs):
        raise ValueError("bad openhands config")

    monkeypatch.setattr(cli_integrations, "sync_openhands_global_config", _boom)
    monkeypatch.setattr(sys, "argv", ["sync-openhands-config"])

    try:
        cli_integrations.sync_openhands_config_cli()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert "bad openhands config" in out
