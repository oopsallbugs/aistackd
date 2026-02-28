from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ai_stack.integrations.adapters.openhands import OpenHandsAdapter
from ai_stack.integrations.core.types import IntegrationContext


class _FakeClient:
    def __init__(self, *, healthy: bool = True, chat_content: str = "ok", raise_on_chat: bool = False):
        self._healthy = healthy
        self._chat_content = chat_content
        self._raise_on_chat = raise_on_chat

    def health_check(self) -> bool:
        return self._healthy

    def chat(self, messages, **kwargs):
        _ = (messages, kwargs)
        if self._raise_on_chat:
            raise RuntimeError("chat failure")
        return SimpleNamespace(content=self._chat_content)


def _context(
    *,
    project_root: Path,
    llama_api_url: str = "http://127.0.0.1:8080",
    default_model: str | None = "m.gguf",
    client=None,
) -> IntegrationContext:
    fake_client = client or _FakeClient(healthy=True)
    return IntegrationContext(
        project_root=project_root,
        llama_api_url=llama_api_url,
        default_model=default_model,
        create_client=lambda **kwargs: fake_client,
    )


def test_validate_success(tmp_path: Path) -> None:
    adapter = OpenHandsAdapter()
    result = adapter.validate(_context(project_root=tmp_path))
    assert result.ok is True
    assert result.messages == []


def test_validate_reports_invalid_state(tmp_path: Path) -> None:
    adapter = OpenHandsAdapter()
    bad_root = tmp_path / "missing"
    result = adapter.validate(
        _context(
            project_root=bad_root,
            llama_api_url="localhost:8080",
            default_model=None,
            client=_FakeClient(healthy=False),
        )
    )
    assert result.ok is False
    assert "llama_api_url must be an http(s) URL" in result.messages
    assert "default_model is not configured" in result.messages
    assert any("project_root does not exist" in msg for msg in result.messages)
    assert "llama endpoint is not healthy" in result.messages


def test_build_runtime_config(tmp_path: Path) -> None:
    adapter = OpenHandsAdapter()
    runtime = adapter.build_runtime_config(_context(project_root=tmp_path))
    assert runtime.name == "openhands"
    assert runtime.values["provider"] == "llama.cpp-local"
    assert runtime.values["api_base"] == "http://127.0.0.1:8080/v1"
    assert runtime.values["model"] == "m.gguf"
    assert runtime.values["workspace_root"] == str(tmp_path.resolve())


def test_smoke_test_success_and_failure(tmp_path: Path) -> None:
    adapter = OpenHandsAdapter()
    success = adapter.smoke_test(_context(project_root=tmp_path, client=_FakeClient(healthy=True)))
    assert success.ok is True

    failure = adapter.smoke_test(_context(project_root=tmp_path, client=_FakeClient(healthy=False)))
    assert failure.ok is False
