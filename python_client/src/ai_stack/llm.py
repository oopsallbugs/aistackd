"""LLM client for the local llama.cpp-compatible API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

import requests

from ai_stack.core.config import config


@dataclass
class LLMResponse:
    """Chat completion response container."""

    content: str
    model: str = ""
    tokens_used: int = 0
    finish_reason: str = ""
    raw_response: Optional[Dict[str, Any]] = None


class LLMClient:
    """LLM client for a llama.cpp server using runtime configuration."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        api_base = (base_url or config.server.llama_api_url).rstrip("/")
        self.base_url = api_base
        self.server_base_url = api_base[:-3] if api_base.endswith("/v1") else api_base
        self.model = model or config.model.default_model
        self.session = requests.Session()
        self.session.timeout = 30

    def _build_payload(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        return {
            "model": kwargs.get("model", self.model) or "default",
            "messages": messages,
            "temperature": kwargs.get("temperature", config.model.temperature),
            "top_p": kwargs.get("top_p", config.model.top_p),
            "min_p": kwargs.get("min_p", config.model.min_p),
            "max_tokens": kwargs.get("max_tokens", config.model.max_tokens),
            "repeat_penalty": kwargs.get("repeat_penalty", config.model.repeat_penalty),
            "stream": kwargs.get("stream", False),
        }

    @staticmethod
    def _parse_sse_data_line(line: bytes) -> Optional[Dict[str, Any]]:
        if not line:
            return None

        text = line.decode("utf-8")
        if not text.startswith("data: "):
            return None

        data = text[6:]
        if data.strip() == "[DONE]":
            return None

        try:
            return json.loads(data)
        except ValueError:
            return None

    def health_check(self) -> bool:
        """Check if server is healthy."""
        try:
            response = self.session.get(f"{self.server_base_url}/health", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def wait_for_server(self, timeout: int = 60) -> bool:
        """Wait for server to become available."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.health_check():
                return True
            time.sleep(1)
        return False

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """Run a non-streaming chat completion."""
        if not self.health_check():
            if not self.wait_for_server(10):
                raise ConnectionError("LLM server is not available")

        payload = self._build_payload(messages, **kwargs)
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=kwargs.get("timeout", 120),
        )
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice.get("message", {})

        return LLMResponse(
            content=message.get("content", "").strip(),
            model=data.get("model", ""),
            tokens_used=data.get("usage", {}).get("total_tokens", 0),
            finish_reason=choice.get("finish_reason", ""),
            raw_response=data,
        )

    def stream_chat(self, messages: List[Dict[str, str]], **kwargs) -> Generator[Dict[str, Any], None, None]:
        """Run a streaming chat completion."""
        payload = self._build_payload(messages, **kwargs)
        payload["stream"] = True

        with self.session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            stream=True,
            timeout=kwargs.get("timeout", 300),
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines():
                parsed = self._parse_sse_data_line(line)
                if parsed is not None:
                    yield parsed

    def quick_chat(self, prompt: str, **kwargs) -> str:
        """Quick one-shot chat."""
        response = self.chat([{"role": "user", "content": prompt}], **kwargs)
        return response.content

    def get_models(self) -> List[str]:
        """Get available models from server."""
        try:
            response = self.session.get(f"{self.base_url}/models", timeout=5)
            response.raise_for_status()
            data = response.json()
            return [model["id"] for model in data.get("data", [])]
        except requests.RequestException:
            return []

    def get_model_info(self) -> Dict[str, Any]:
        """Get server model information."""
        try:
            response = self.session.get(f"{self.server_base_url}/props", timeout=5)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            pass
        return {}


def create_client(model: Optional[str] = None) -> LLMClient:
    """Create an LLM client with runtime configuration."""
    return LLMClient(model=model)


def quick_chat(prompt: str, **kwargs) -> str:
    """Quick one-shot chat using the default client."""
    client = create_client()
    return client.quick_chat(prompt, **kwargs)
