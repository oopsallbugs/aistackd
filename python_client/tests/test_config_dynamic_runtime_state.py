from __future__ import annotations

from ai_stack.core.config import AiStackConfig


def _make_config(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True)
    paths = {
        "project_root": str(project_root),
        "llama_cpp_dir": str(project_root / "llama.cpp"),
        "models_dir": str(project_root / "models"),
    }
    user_config = {
        "gpu": {
            "vendor": "cpu",
            "target": "cpu",
            "hsa_override_gfx_version": "",
            "layers": 0,
        },
        "server": {
            "host": "127.0.0.1",
            "port": 8080,
            "rag_host": "127.0.0.1",
            "rag_port": 8081,
        },
        "model": {
            "default_model": None,
            "temperature": 1.0,
            "top_p": 0.95,
            "min_p": 0.01,
            "max_tokens": 2000,
            "repeat_penalty": 1.0,
            "context_size": 32768,
        },
        "paths": paths,
    }
    return AiStackConfig(user_config=user_config)


def test_server_urls_are_dynamic_when_host_or_port_change(tmp_path) -> None:
    cfg = _make_config(tmp_path)

    assert cfg.server.llama_url == "http://127.0.0.1:8080"
    assert cfg.server.llama_api_url == "http://127.0.0.1:8080/v1"

    cfg.server.host = "0.0.0.0"
    cfg.server.port = 9090

    assert cfg.server.llama_url == "http://0.0.0.0:9090"
    assert cfg.server.llama_api_url == "http://0.0.0.0:9090/v1"


def test_runtime_state_properties_recompute_after_filesystem_changes(tmp_path) -> None:
    cfg = _make_config(tmp_path)

    assert cfg.is_llama_built is False
    assert cfg.has_models is False

    cfg.llama_server_binary.parent.mkdir(parents=True, exist_ok=True)
    cfg.llama_server_binary.write_text("x", encoding="utf-8")
    cfg.paths.models_dir.mkdir(parents=True, exist_ok=True)
    (cfg.paths.models_dir / "demo.gguf").write_text("x", encoding="utf-8")

    assert cfg.is_llama_built is True
    assert cfg.has_models is True
