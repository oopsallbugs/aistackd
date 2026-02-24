from __future__ import annotations

import sys
from pathlib import Path

import ai_stack.cli.integrations as cli_integrations
from ai_stack.integrations.frontends.opencode.sync import OpenCodeSyncResult


def test_sync_cli_dry_run_prints_payload_and_warnings(monkeypatch, capsys, tmp_path: Path) -> None:
    fake_result = OpenCodeSyncResult(
        path=tmp_path / "opencode.json",
        written=False,
        warnings=["warning one"],
        validation_ok=False,
        validation_messages=["warning one"],
        payload={"provider": {"llama.cpp": {}}, "model": "llama.cpp/default"},
    )

    monkeypatch.setattr(cli_integrations, "sync_opencode_global_config", lambda **kwargs: fake_result)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sync-opencode-config",
            "--dry-run",
            "--print",
            "--sync-tools",
            "--sync-agents",
        ],
    )

    rc = cli_integrations.sync_opencode_config_cli()

    out = capsys.readouterr().out
    assert rc == 0
    assert '"provider"' in out
    assert "warning one" in out
    assert "Dry run complete" in out


def test_sync_cli_value_error_returns_exit_1(monkeypatch, capsys) -> None:
    def _boom(**kwargs):
        raise ValueError("bad config")

    monkeypatch.setattr(cli_integrations, "sync_opencode_global_config", _boom)
    monkeypatch.setattr(sys, "argv", ["sync-opencode-config"])

    try:
        cli_integrations.sync_opencode_config_cli()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert "bad config" in out
