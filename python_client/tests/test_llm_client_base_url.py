from __future__ import annotations

from ai_stack.llm import LLMClient


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=5):
        self.urls.append((url, timeout))
        if url.endswith("/props"):
            return _FakeResponse(status_code=200, payload={"ok": True})
        return _FakeResponse(status_code=200, payload={})


def test_llm_client_health_and_props_use_client_base_url() -> None:
    client = LLMClient(base_url="http://127.0.0.1:9000/v1")
    fake_session = _FakeSession()
    client.session = fake_session

    assert client.health_check() is True
    assert client.get_model_info() == {"ok": True}
    assert fake_session.urls[0][0] == "http://127.0.0.1:9000/health"
    assert fake_session.urls[1][0] == "http://127.0.0.1:9000/props"
