from __future__ import annotations

import subprocess
from types import SimpleNamespace

from ai_stack.llama.build import build_llama_cpp


def test_build_llama_cpp_surfaces_stderr_on_cmake_failure(monkeypatch, tmp_path, capsys) -> None:
    llama_cpp_dir = tmp_path / "llama.cpp"
    llama_cpp_dir.mkdir(parents=True)

    config = SimpleNamespace(
        is_llama_built=False,
        gpu=SimpleNamespace(vendor="cpu", cmake_flags=[], hsa_override_gfx_version=""),
        paths=SimpleNamespace(llama_cpp_dir=llama_cpp_dir),
        llama_server_binary=llama_cpp_dir / "build" / "bin" / "llama-server",
    )

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "cmake":
            raise subprocess.CalledProcessError(1, cmd, output="cmake out", stderr="cmake err")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr("ai_stack.llama.build.subprocess.run", fake_run)

    ok = build_llama_cpp(config)

    assert ok is False
    out = capsys.readouterr().out
    assert "Build failed" in out
    assert "cmake err" in out
