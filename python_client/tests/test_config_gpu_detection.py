from __future__ import annotations

from dataclasses import dataclass

from ai_stack.core.config import GPUConfig


@dataclass
class _RunResult:
    returncode: int = 0
    stdout: str = ""


def test_amd_detection_non_interactive_uses_fallback_target(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[0] == "nvidia-smi":
            return _RunResult(returncode=1, stdout="")
        if cmd[0] == "rocminfo":
            return _RunResult(returncode=0, stdout="Agent 2 Name: gfx")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr("ai_stack.llama.detect_gpu.subprocess.run", fake_run)
    monkeypatch.setattr("ai_stack.llama.detect_gpu.os.path.exists", lambda p: p == "/dev/kfd")
    gpu = GPUConfig(vendor="auto", target="", hsa_override_gfx_version="", layers=0)
    gpu._detect_linux_gpu(fallback_amd_target="gfx1030")

    assert gpu.vendor == "amd"
    assert gpu.target == "gfx1030"
    assert gpu.hsa_override_gfx_version == "10.3.0"
    assert gpu.layers == 99


def test_amd_detection_uses_default_fallback_when_not_set(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[0] == "nvidia-smi":
            return _RunResult(returncode=1, stdout="")
        if cmd[0] == "rocminfo":
            return _RunResult(returncode=0, stdout="Agent 2 Name: gfx")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr("ai_stack.llama.detect_gpu.subprocess.run", fake_run)
    monkeypatch.setattr("ai_stack.llama.detect_gpu.os.path.exists", lambda p: p == "/dev/kfd")

    gpu = GPUConfig(vendor="auto", target="", hsa_override_gfx_version="", layers=0)
    gpu._detect_linux_gpu()

    assert gpu.vendor == "amd"
    assert gpu.target == "gfx1100"
    assert gpu.hsa_override_gfx_version == "11.0.0"
    assert gpu.layers == 99
