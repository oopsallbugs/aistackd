"""OpenCode integration adapter."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_stack.integrations.core.types import (
    IntegrationContext,
    IntegrationRuntimeConfig,
    IntegrationSmokeResult,
    IntegrationValidationResult,
)
from ai_stack.integrations.adapters.opencode.types import (
    OpenCodeModelEntry,
    OpenCodeModelLimit,
    OpenCodeProvider,
    OpenCodeProviderOptions,
    OpenCodeRuntimeValues,
)


class OpenCodeAdapter:
    """Adapter that maps ai-stack runtime into OpenCode-compatible config."""

    name = "opencode"
    _provider_key = "llama.cpp"
    _provider_name = "llama.cpp (local)"
    _provider_npm = "@ai-sdk/openai-compatible"
    _default_output_tokens = 8192
    _default_schema = "https://opencode.ai/config.json"

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

        if context.default_model:
            get_models = getattr(client, "get_models", None)
            if callable(get_models):
                try:
                    loaded = list(get_models() or [])
                except Exception as exc:  # pragma: no cover - defensive runtime boundary
                    messages.append(f"could not verify loaded models: {exc}")
                else:
                    if loaded and context.default_model not in loaded:
                        messages.append(
                            f"default model '{context.default_model}' not found in loaded models"
                        )

        return IntegrationValidationResult(ok=not messages, messages=messages)

    @staticmethod
    def _slugify_model(model_name: str) -> str:
        lowered = model_name.strip().lower().replace(".gguf", "")
        normalized = []
        prev_dash = False
        for ch in lowered:
            if ch.isalnum():
                normalized.append(ch)
                prev_dash = False
            else:
                if not prev_dash:
                    normalized.append("-")
                prev_dash = True
        slug = "".join(normalized).strip("-")
        return slug or "default"

    @classmethod
    def _model_entry(cls, model_name: str, context_limit: int) -> OpenCodeModelEntry:
        return OpenCodeModelEntry(
            name=model_name,
            tools=True,
            limit=OpenCodeModelLimit(
                context=context_limit,
                output=cls._default_output_tokens,
            ),
        )

    def _discover_models(self, context: IntegrationContext) -> List[str]:
        model_names: List[str] = []

        if context.default_model:
            model_names.append(context.default_model)

        client = self._create_client(context)
        get_models = getattr(client, "get_models", None)
        if callable(get_models):
            try:
                loaded_models = list(get_models() or [])
            except Exception:  # pragma: no cover - defensive runtime boundary
                loaded_models = []
            for model_name in loaded_models:
                if model_name and model_name not in model_names:
                    model_names.append(model_name)

        if not model_names:
            model_names.append("default")

        return model_names

    def _build_provider_config(self, context: IntegrationContext) -> Dict[str, OpenCodeProvider]:
        context_limit = 32768
        try:
            client = self._create_client(context)
            get_model_info = getattr(client, "get_model_info", None)
            if callable(get_model_info):
                props = get_model_info() or {}
                n_ctx = props.get("n_ctx")
                if isinstance(n_ctx, int) and n_ctx > 0:
                    context_limit = n_ctx
        except Exception:  # pragma: no cover - defensive runtime boundary
            pass

        models: Dict[str, OpenCodeModelEntry] = {}
        for model_name in self._discover_models(context):
            model_key = self._slugify_model(model_name)
            models[model_key] = self._model_entry(model_name=model_name, context_limit=context_limit)

        provider = OpenCodeProvider(
            npm=self._provider_npm,
            name=self._provider_name,
            options=OpenCodeProviderOptions(baseURL=f"{context.llama_api_url.rstrip('/')}/v1"),
            models=models,
        )
        return {self._provider_key: provider}

    def build_runtime_config(self, context: IntegrationContext) -> IntegrationRuntimeConfig:
        base_url = f"{context.llama_api_url.rstrip('/')}/v1"
        discovered = self._discover_models(context)
        selected_model = discovered[0]
        selected_key = self._slugify_model(selected_model)
        provider_config = self._build_provider_config(context)
        payload = OpenCodeRuntimeValues(
            provider="openai",
            provider_key=self._provider_key,
            provider_config=provider_config[self._provider_key],
            base_url=base_url,
            model=selected_model,
        )
        values = asdict(payload)
        values["provider"] = {key: asdict(config) for key, config in provider_config.items()}
        values["selected"] = f"{self._provider_key}/{selected_key}"
        return IntegrationRuntimeConfig(name=self.name, values=values)

    def build_project_config(self, context: IntegrationContext) -> Dict[str, Any]:
        """Build an opencode.json-compatible config payload."""
        runtime = self.build_runtime_config(context)
        return {
            "$schema": self._default_schema,
            "provider": runtime.values["provider"],
            "model": runtime.values["selected"],
        }

    def write_project_config(self, context: IntegrationContext, path: Optional[Path] = None) -> Path:
        """
        Write an opencode.json file for the current project.

        Existing config keys are preserved except provider/model entries, which are updated.
        """
        target_path = path or (context.project_root / "opencode.json")
        existing: Dict[str, Any] = {}
        if target_path.exists():
            try:
                loaded = json.loads(target_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:  # pragma: no cover - defensive runtime boundary
                existing = {}

        payload = self.build_project_config(context)
        merged = dict(existing)
        merged.setdefault("$schema", payload["$schema"])
        merged["provider"] = payload["provider"]
        merged["model"] = payload["model"]

        target_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return target_path

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


__all__ = ["OpenCodeAdapter"]
