from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from ai_stack.core.exceptions import ServerError
from ai_stack.llama.server import start_llama_server


class _FakeProcess:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


def test_start_llama_server_times_out_and_raises_server_error(monkeypatch, tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_text("x", encoding="utf-8")

    fake_process = _FakeProcess()

    monkeypatch.setattr("ai_stack.llama.server.subprocess.Popen", lambda *a, **k: fake_process)
    monkeypatch.setattr(
        "ai_stack.llama.server.requests.get",
        lambda *a, **k: (_ for _ in ()).throw(requests.RequestException("down")),
    )
    monkeypatch.setattr("ai_stack.llama.server.time.sleep", lambda *_: None)

    config = SimpleNamespace(
        is_llama_built=True,
        paths=SimpleNamespace(models_dir=tmp_path),
        llama_server_binary=tmp_path / "llama-server",
        server=SimpleNamespace(host="0.0.0.0", port=8080, llama_url="http://127.0.0.1:8080"),
        model=SimpleNamespace(context_size=4096),
        gpu=SimpleNamespace(vendor="cpu", hsa_override_gfx_version="", layers=0),
    )
    registry = SimpleNamespace(scan_models_dir=lambda: None, manifest={"models": []}, get_mmproj_for_model=lambda _: None)

    with pytest.raises(ServerError, match="failed to start"):
        start_llama_server(config=config, registry=registry, model_path=str(model_path))

    assert fake_process.terminated is True


def test_start_llama_server_command_uses_configured_host_and_port(monkeypatch, tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_text("x", encoding="utf-8")

    captured = {}

    class _Process:
        def terminate(self):
            return None

    def _fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr("ai_stack.llama.server.subprocess.Popen", _fake_popen)
    monkeypatch.setattr("ai_stack.llama.server.requests.get", lambda *a, **k: SimpleNamespace(status_code=200))
    monkeypatch.setattr("ai_stack.llama.server.time.sleep", lambda *_: None)

    config = SimpleNamespace(
        is_llama_built=True,
        paths=SimpleNamespace(models_dir=tmp_path),
        llama_server_binary=tmp_path / "llama-server",
        server=SimpleNamespace(host="127.0.0.1", port=9999, llama_url="http://127.0.0.1:9999"),
        model=SimpleNamespace(context_size=4096),
        gpu=SimpleNamespace(vendor="cpu", hsa_override_gfx_version="", layers=0),
    )
    registry = SimpleNamespace(scan_models_dir=lambda: None, manifest={"models": []}, get_mmproj_for_model=lambda _: None)

    start_llama_server(config=config, registry=registry, model_path=str(model_path))

    cmd = captured["cmd"]
    assert "--host" in cmd
    assert "127.0.0.1" in cmd
    assert "--port" in cmd
    assert "9999" in cmd
