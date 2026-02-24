from __future__ import annotations

import sys
from types import SimpleNamespace

import ai_stack.cli as cli
import ai_stack.cli.download as cli_download


def test_download_model_list_accepts_hf_url(monkeypatch, capsys) -> None:
    captured = {}

    class FakeManager:
        def list_huggingface_files(self, repo_id: str):
            from ai_stack.stack.manager import SetupManager

            captured["normalized_repo"] = SetupManager.normalize_hf_repo_id(repo_id)
            return SimpleNamespace(
                repo_id=captured["normalized_repo"],
                pipeline_tag=None,
                tags=[],
                sha=None,
                gguf_files=[],
                mmproj_files=[],
                cache_event="miss",
            )

        @staticmethod
        def format_cache_event(event: str | None, repo_id: str, revision: str = "main") -> str | None:
            captured["event"] = event
            captured["event_repo"] = repo_id
            return None

        def print_cache_diagnostics(self):
            captured["printed_cache_diagnostics"] = True

    monkeypatch.setattr(cli_download, "SetupManager", FakeManager)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download-model",
            "--list",
            "--cache-diagnostics",
            "https://huggingface.co/TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF",
        ],
    )

    cli.download_model_cli()

    out = capsys.readouterr().out
    assert captured["normalized_repo"] == "TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF"
    assert captured["event"] == "miss"
    assert captured["event_repo"] == captured["normalized_repo"]
    assert captured["printed_cache_diagnostics"] is True
    assert "workers:" in out


def test_download_model_invalid_repo_exits_with_friendly_error(monkeypatch, capsys) -> None:
    class FakeManager:
        def download_from_huggingface(self, **kwargs):
            raise ValueError("bad repo")

        @staticmethod
        def format_cache_event(event: str | None, repo_id: str, revision: str = "main") -> str | None:
            return None

        def print_cache_diagnostics(self):
            raise AssertionError("should not print diagnostics on failure")

    monkeypatch.setattr(cli_download, "SetupManager", FakeManager)
    monkeypatch.setattr(
        sys,
        "argv",
        ["download-model", "not-a-valid-input"],
    )

    try:
        cli.download_model_cli()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert "Invalid HuggingFace repo input" in out


def test_download_model_runtime_failure_exits_with_friendly_error(monkeypatch, capsys) -> None:
    class FakeManager:
        def download_from_huggingface(self, **kwargs):
            raise RuntimeError("temporary network issue")

        @staticmethod
        def format_cache_event(event: str | None, repo_id: str, revision: str = "main") -> str | None:
            return None

        def print_cache_diagnostics(self):
            raise AssertionError("should not print diagnostics on failure")

    monkeypatch.setattr(cli_download, "SetupManager", FakeManager)
    monkeypatch.setattr(
        sys,
        "argv",
        ["download-model", "org/model"],
    )

    try:
        cli.download_model_cli()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert "Download failed unexpectedly: temporary network issue" in out
