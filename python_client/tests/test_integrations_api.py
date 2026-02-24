from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ai_stack import integrations
from ai_stack.integrations.core import IntegrationAdapter, get_adapter, list_adapters
from ai_stack.integrations.core.registry import _clear_registry_for_tests


def test_build_integration_context_uses_runtime_config(monkeypatch) -> None:
    project_root = Path("/tmp/ai-stack-test")
    fake_config = SimpleNamespace(
        paths=SimpleNamespace(project_root=project_root),
        server=SimpleNamespace(llama_url="http://0.0.0.0:8080"),
        model=SimpleNamespace(default_model="demo.gguf"),
    )

    def _fake_create_client(**kwargs):
        _ = kwargs
        return object()

    monkeypatch.setattr(integrations, "config", fake_config)
    monkeypatch.setattr(integrations, "create_client", _fake_create_client)

    context = integrations.build_integration_context()

    assert context.project_root == project_root
    assert context.llama_api_url == "http://0.0.0.0:8080"
    assert context.default_model == "demo.gguf"
    assert context.create_client is _fake_create_client


def test_register_default_adapters_is_idempotent_and_protocol_compliant() -> None:
    _clear_registry_for_tests()

    integrations.register_default_adapters()
    integrations.register_default_adapters()

    names = list_adapters()
    assert names == ["opencode", "tools.readonly_filesystem"]

    for name in names:
        assert isinstance(get_adapter(name), IntegrationAdapter)

    _clear_registry_for_tests()


def test_sync_opencode_project_config_delegates_to_adapter(monkeypatch, tmp_path) -> None:
    written = {}

    class _FakeAdapter:
        def write_project_config(self, context, path=None):
            written["context"] = context
            written["path"] = path
            return tmp_path / "opencode.json"

    monkeypatch.setattr(integrations, "register_default_adapters", lambda: None)
    monkeypatch.setattr(integrations, "get_adapter", lambda name: _FakeAdapter())
    monkeypatch.setattr(integrations, "build_integration_context", lambda: object())

    target = tmp_path / "custom-opencode.json"
    result = integrations.sync_opencode_project_config(path=target)

    assert result == tmp_path / "opencode.json"
    assert written["path"] == target


def test_sync_opencode_global_config_delegates_to_sync_helper(monkeypatch, tmp_path) -> None:
    called = {}

    class _Result:
        path = tmp_path / "opencode.json"
        written = False
        warnings = []
        validation_ok = True
        validation_messages = []
        payload = {}

    def _fake_sync(**kwargs):
        called.update(kwargs)
        return _Result()

    monkeypatch.setattr(integrations, "register_default_adapters", lambda: None)
    monkeypatch.setattr(integrations, "build_integration_context", lambda: object())
    monkeypatch.setattr(integrations, "sync_opencode_global_config_with_defaults", _fake_sync)

    result = integrations.sync_opencode_global_config(
        global_path=tmp_path / "custom.json",
        sync_tools=True,
        sync_agents=True,
        dry_run=True,
    )

    assert result.path == tmp_path / "opencode.json"
    assert called["global_path"] == tmp_path / "custom.json"
    assert called["sync_tools"] is True
    assert called["sync_agents"] is True
    assert called["dry_run"] is True
