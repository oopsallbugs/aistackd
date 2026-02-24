from __future__ import annotations

import sys
from types import SimpleNamespace

import ai_stack.cli as cli
import ai_stack.cli.setup as cli_setup


def test_setup_cli_prints_setup_header_once(monkeypatch, capsys) -> None:
    class FakeManager:
        def setup(self):
            return SimpleNamespace(
                success=True,
                missing_critical=[],
                clone_ok=True,
                build_ok=True,
                has_models=False,
                models_dir="/tmp/models",
            )

    printed = {"summary_calls": 0}

    def _print_summary():
        printed["summary_calls"] += 1

    monkeypatch.setattr(cli_setup, "SetupManager", FakeManager)
    monkeypatch.setattr(cli_setup, "config", SimpleNamespace(print_summary=_print_summary))
    monkeypatch.setattr(sys, "argv", ["setup-stack"])

    try:
        cli.setup_cli()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert out.count("AI Stack Setup") == 1
    assert printed["summary_calls"] == 1


def test_setup_wrapper_unexpected_error_is_user_safe(monkeypatch, capsys) -> None:
    def _boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_setup.setup_install_cmd, "setup_cli", _boom)

    try:
        cli.setup_cli()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert "Setup failed unexpectedly: boom" in out
    assert "Please retry and check logs." in out
