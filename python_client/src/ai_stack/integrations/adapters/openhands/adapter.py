"""OpenHands integration adapter."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, List

from ai_stack.integrations.adapters.openhands.types import OpenHandsRuntimeValues
from ai_stack.integrations.core.types import (
    IntegrationContext,
    IntegrationRuntimeConfig,
    IntegrationSmokeResult,
    IntegrationValidationResult,
)


class OpenHandsAdapter:
    """Adapter that maps ai-stack runtime into OpenHands-compatible config."""

    name = "openhands"
    _provider_name = "llama.cpp-local"

    @staticmethod
    def _create_client(context: IntegrationContext) -> Any:
        try:
            return context.create_client(model=context.default_model)
        except TypeError:
            return context.create_client()

    def validate(self, context: IntegrationContext) -> IntegrationValidationResult:
        messages: List[str] = []

        if not context.llama_api_url:
            messages.append("llama_api_url is required")
        elif not context.llama_api_url.startswith("http"):
            messages.append("llama_api_url must be an http(s) URL")

        if not context.default_model:
            messages.append("default_model is not configured")

        project_root = context.project_root.resolve()
        if not project_root.exists():
            messages.append(f"project_root does not exist: {project_root}")
        elif not project_root.is_dir():
            messages.append(f"project_root is not a directory: {project_root}")

        client = self._create_client(context)
        health_check = getattr(client, "health_check", None)
        if callable(health_check):
            try:
                healthy = bool(health_check())
            except Exception as exc:  # pragma: no cover - defensive runtime boundary
                messages.append(f"health check failed: {exc}")
            else:
                if not healthy:
                    messages.append("llama endpoint is not healthy")
        else:
            messages.append("client does not expose health_check()")

        return IntegrationValidationResult(ok=not messages, messages=messages)

    def build_runtime_config(self, context: IntegrationContext) -> IntegrationRuntimeConfig:
        selected_model = context.default_model or "default"
        payload = OpenHandsRuntimeValues(
            provider=self._provider_name,
            llama_base_url=context.llama_api_url.rstrip("/"),
            api_base=f"{context.llama_api_url.rstrip('/')}/v1",
            model=selected_model,
            workspace_root=str(context.project_root.resolve()),
        )
        return IntegrationRuntimeConfig(name=self.name, values=asdict(payload))

    def smoke_test(self, context: IntegrationContext) -> IntegrationSmokeResult:
        client = self._create_client(context)
        health_check = getattr(client, "health_check", None)
        if callable(health_check):
            try:
                if not health_check():
                    return IntegrationSmokeResult(ok=False, details="llama endpoint health check failed")
            except Exception as exc:  # pragma: no cover - defensive runtime boundary
                return IntegrationSmokeResult(ok=False, details=f"health probe error: {exc}")

        try:
            response = client.chat(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                max_tokens=8,
                temperature=0.0,
            )
            content = getattr(response, "content", "")
            if not isinstance(content, str) or not content.strip():
                return IntegrationSmokeResult(ok=False, details="chat probe returned empty content")
            return IntegrationSmokeResult(ok=True, details=f"chat probe succeeded: {content.strip()}")
        except Exception as exc:
            return IntegrationSmokeResult(ok=False, details=f"chat probe failed: {exc}")


__all__ = ["OpenHandsAdapter"]
