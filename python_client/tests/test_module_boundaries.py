from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

from ai_stack.core.logging import LOG_ENV_FLAG, emit_event
from ai_stack.core.errors import exit_with_unexpected_error
from ai_stack.stack.manager import SetupManager


def test_setup_manager_delegates_llama_build_and_start(monkeypatch) -> None:
    clone_calls = {}
    build_calls = {}
    start_calls = {}

    def fake_clone_llama_cpp(*, config, force=False):
        clone_calls["config"] = config
        clone_calls["force"] = force
        return True

    def fake_build_llama_cpp(*, config):
        build_calls["config"] = config
        return True

    def fake_start_llama_server(**kwargs):
        start_calls.update(kwargs)
        return "process"

    monkeypatch.setattr("ai_stack.stack.manager.clone_llama_cpp", fake_clone_llama_cpp)
    monkeypatch.setattr("ai_stack.stack.manager.build_llama_cpp", fake_build_llama_cpp)
    monkeypatch.setattr("ai_stack.stack.manager.start_llama_server", fake_start_llama_server)

    manager = object.__new__(SetupManager)
    manager.config = object()
    manager.registry = object()

    assert manager.clone_llama_cpp(force=True) is True
    assert manager.build_llama_cpp() is True
    assert manager.start_server(model_path="m.gguf", mmproj_path="p.gguf") == "process"

    assert clone_calls == {"config": manager.config, "force": True}
    assert build_calls == {"config": manager.config}
    assert start_calls["config"] is manager.config
    assert start_calls["registry"] is manager.registry
    assert start_calls["model_path"] == "m.gguf"
    assert start_calls["mmproj_path"] == "p.gguf"


def test_core_config_has_no_registry_setup_or_cli_imports() -> None:
    core_config = importlib.import_module("ai_stack.core.config")

    src = Path(core_config.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    forbidden_prefixes = ("ai_stack.models", "ai_stack.setup", "ai_stack.cli")
    imported = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    for name in imported:
        assert not name.startswith(forbidden_prefixes)


def test_cli_command_modules_do_not_import_stack_manager_directly() -> None:
    command_modules = [
        "python_client/src/ai_stack/cli/server_start.py",
        "python_client/src/ai_stack/cli/server_status.py",
        "python_client/src/ai_stack/cli/server_stop.py",
        "python_client/src/ai_stack/cli/setup_install.py",
        "python_client/src/ai_stack/cli/setup_deps.py",
        "python_client/src/ai_stack/cli/setup_uninstall.py",
    ]

    for module_path in command_modules:
        src = Path(module_path).read_text(encoding="utf-8")
        tree = ast.parse(src)

        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        for name in imported:
            assert name != "ai_stack.stack.manager"
            assert not name.startswith("ai_stack.stack.manager")


def test_emit_event_is_disabled_by_default(monkeypatch, capsys) -> None:
    monkeypatch.delenv(LOG_ENV_FLAG, raising=False)
    emit_event("test.event", foo="bar")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_emit_event_outputs_json_when_enabled(monkeypatch, capsys) -> None:
    monkeypatch.setenv(LOG_ENV_FLAG, "1")
    emit_event("test.event", foo="bar")
    captured = capsys.readouterr()
    assert captured.err.startswith("[ai_stack.event] ")
    payload = json.loads(captured.err[len("[ai_stack.event] ") :].strip())
    assert payload["event"] == "test.event"
    assert payload["foo"] == "bar"
    assert payload["schema_version"] == 1


def test_exit_with_unexpected_error_has_consistent_shape(capsys) -> None:
    try:
        exit_with_unexpected_error(command="Download", exc=RuntimeError("network down"))
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert "Download failed unexpectedly: network down" in out
    assert "Please retry and check logs." in out
