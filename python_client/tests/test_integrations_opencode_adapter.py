from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ai_stack.integrations.core.types import IntegrationContext
from ai_stack.integrations.adapters.opencode import OpenCodeAdapter


class _FakeClient:
    def __init__(
        self,
        *,
        healthy: bool = True,
        loaded_models=None,
        chat_content: str = "ok",
        raise_on_chat: bool = False,
    ):
        self._healthy = healthy
        self._loaded_models = loaded_models or []
        self._chat_content = chat_content
        self._raise_on_chat = raise_on_chat

    def health_check(self) -> bool:
        return self._healthy

    def get_models(self):
        return list(self._loaded_models)

    def chat(self, messages, **kwargs):
        _ = (messages, kwargs)
        if self._raise_on_chat:
            raise RuntimeError("chat failure")
        return SimpleNamespace(content=self._chat_content)


def _context(*, llama_api_url: str = "http://127.0.0.1:8080", default_model: str | None = "m.gguf", client=None):
    fake_client = client or _FakeClient(healthy=True, loaded_models=["m.gguf"])

    def _create_client(**kwargs):
        _ = kwargs
        return fake_client

    return IntegrationContext(
        project_root=Path("."),
        llama_api_url=llama_api_url,
        default_model=default_model,
        create_client=_create_client,
    )


def test_validate_success() -> None:
    adapter = OpenCodeAdapter()
    result = adapter.validate(_context())

    assert result.ok is True
    assert result.messages == []


def test_validate_reports_invalid_url_and_missing_default_model() -> None:
    adapter = OpenCodeAdapter()
    result = adapter.validate(_context(llama_api_url="localhost:8080", default_model=None))

    assert result.ok is False
    assert "llama_api_url must be an http(s) URL" in result.messages
    assert "default_model is not configured" in result.messages


def test_validate_reports_unhealthy_endpoint() -> None:
    adapter = OpenCodeAdapter()
    context = _context(client=_FakeClient(healthy=False, loaded_models=["m.gguf"]))

    result = adapter.validate(context)

    assert result.ok is False
    assert "llama endpoint is not healthy" in result.messages


def test_validate_accepts_create_client_without_model_kwarg() -> None:
    adapter = OpenCodeAdapter()
    client = _FakeClient(healthy=True, loaded_models=["m.gguf"])

    def _create_client_no_args():
        return client

    context = IntegrationContext(
        project_root=Path("."),
        llama_api_url="http://127.0.0.1:8080",
        default_model="m.gguf",
        create_client=_create_client_no_args,
    )

    result = adapter.validate(context)

    assert result.ok is True


def test_build_runtime_config_uses_openai_compatible_payload() -> None:
    adapter = OpenCodeAdapter()
    runtime = adapter.build_runtime_config(_context(llama_api_url="http://0.0.0.0:8080"))

    assert runtime.name == "opencode"
    assert runtime.values["provider"] != {}
    assert "llama.cpp" in runtime.values["provider"]
    assert runtime.values["base_url"] == "http://0.0.0.0:8080/v1"
    assert runtime.values["model"] == "m.gguf"
    assert runtime.values["selected"] == "llama.cpp/m"
    assert runtime.values["api_format"] == "openai-compatible"


def test_build_runtime_config_falls_back_to_default_model_token() -> None:
    adapter = OpenCodeAdapter()
    runtime = adapter.build_runtime_config(_context(default_model=None, client=_FakeClient(loaded_models=[])))

    assert runtime.values["model"] == "default"
    assert runtime.values["selected"] == "llama.cpp/default"


def test_build_runtime_config_includes_loaded_model_options() -> None:
    adapter = OpenCodeAdapter()
    context = _context(
        default_model="primary.gguf",
        client=_FakeClient(healthy=True, loaded_models=["primary.gguf", "secondary.gguf"]),
    )
    runtime = adapter.build_runtime_config(context)

    provider = runtime.values["provider"]["llama.cpp"]
    assert "primary" in provider["models"]
    assert "secondary" in provider["models"]
    assert provider["models"]["secondary"]["name"] == "secondary.gguf"


def test_write_project_config_merges_existing_content(tmp_path) -> None:
    adapter = OpenCodeAdapter()
    existing_path = tmp_path / "opencode.json"
    existing_path.write_text(
        json.dumps({"$schema": "https://opencode.ai/config.json", "instructions": ["docs/*.md"]}),
        encoding="utf-8",
    )

    context = IntegrationContext(
        project_root=tmp_path,
        llama_api_url="http://127.0.0.1:8080",
        default_model="m.gguf",
        create_client=lambda **kwargs: _FakeClient(loaded_models=["m.gguf"]),
    )
    written = adapter.write_project_config(context, path=existing_path)
    payload = json.loads(written.read_text(encoding="utf-8"))

    assert written == existing_path
    assert payload["instructions"] == ["docs/*.md"]
    assert payload["model"] == "llama.cpp/m"
    assert "llama.cpp" in payload["provider"]


def test_smoke_test_success_and_failure_paths() -> None:
    adapter = OpenCodeAdapter()

    success = adapter.smoke_test(_context(client=_FakeClient(healthy=True, loaded_models=["m.gguf"])))
    assert success.ok is True
    assert "chat probe succeeded" in success.details

    failure = adapter.smoke_test(_context(client=_FakeClient(healthy=False, loaded_models=["m.gguf"])))
    assert failure.ok is False
    assert "health check failed" in failure.details
