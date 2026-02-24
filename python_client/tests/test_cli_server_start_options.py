from __future__ import annotations

import sys
from types import SimpleNamespace

import ai_stack.cli as cli
import ai_stack.cli.server as cli_server


class _FakeServerConfig:
    def __init__(self):
        self.host = "0.0.0.0"
        self.port = 8080

    @property
    def llama_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def test_server_start_host_port_are_reflected_in_output(monkeypatch, capsys, tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_text("x", encoding="utf-8")

    fake_config = SimpleNamespace(
        model=SimpleNamespace(default_model=None),
        paths=SimpleNamespace(models_dir=tmp_path, project_root=tmp_path),
        server=_FakeServerConfig(),
        resolve_model_path=lambda model: model_path if model == "model.gguf" else None,
        get_available_models=lambda: [{"name": "model.gguf", "size_human": "1.0 MB"}],
    )

    started = {}

    class FakeManager:
        pass

    def _fake_start_foreground(manager, chosen_model_path: str):
        started["model_path"] = chosen_model_path

    monkeypatch.setattr(cli_server, "config", fake_config)
    monkeypatch.setattr(cli_server, "SetupManager", FakeManager)
    monkeypatch.setattr(cli_server, "_start_foreground_server", _fake_start_foreground)
    monkeypatch.setattr(sys, "argv", ["server-start", "model.gguf", "--host", "127.0.0.1", "--port", "9999"])

    cli.start_server_cli()

    out = capsys.readouterr().out
    assert "Custom endpoint: http://127.0.0.1:9999" in out
    assert started["model_path"] == str(model_path)
