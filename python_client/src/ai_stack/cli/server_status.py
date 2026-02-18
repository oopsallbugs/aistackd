"""Status command logic for server CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import requests


class _ModelConfigLike(Protocol):
    default_model: Optional[str]


class _ConfigLike(Protocol):
    model: _ModelConfigLike

    def print_summary(self, show_header: bool = True) -> None: ...
    def get_available_models(self) -> list[dict[str, object]]: ...


class _ClientLike(Protocol):
    def health_check(self) -> bool: ...
    def get_models(self) -> list[str]: ...
    def get_model_info(self) -> dict[str, Any]: ...


def status_cli(
    *,
    config: _ConfigLike,
    create_client: Callable[[], _ClientLike],
    extract_context_size: Callable[[dict[str, Any]], Optional[int]],
    print_cli_header: Callable[[str], None],
    print_section: Callable[[str], None],
):
    """CLI for checking status."""
    print_cli_header("AI Stack Status")

    config.print_summary(show_header=False)

    client = create_client()
    if client.health_check():
        print_section("✅ Server is running")
        try:
            models = client.get_models()
            if models:
                print(f"   Loaded models: {', '.join(models)}")

            model_info = client.get_model_info()
            if model_info:
                context_size = extract_context_size(model_info)
                if context_size is not None:
                    print(f"   Context size: {context_size}")
                else:
                    print("   Context size: unknown (/props did not include a recognized context field)")
        except (requests.RequestException, ValueError, TypeError, KeyError, OSError) as exc:
            print(f"   Could not get model info: {exc}")
    else:
        print_section("❌ Server is not running")
        print_section("To start the server:")
        models = config.get_available_models()
        if models:
            if config.model.default_model:
                default_name = Path(config.model.default_model).name
                print(f"  server-start              # Use default: {default_name}")
                print("  server-start <model_name> # Use a different model")
            else:
                print(f"  server-start {models[0]['name']}")
            print("  server-start --list        # See all models")
        else:
            print("  No models available. Download a model first:")
            print("  download-model <namespace/repo or hf-url>")


__all__ = ["status_cli"]
