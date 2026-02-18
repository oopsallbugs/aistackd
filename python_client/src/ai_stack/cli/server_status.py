"""Status command logic for server CLI."""

from __future__ import annotations

from pathlib import Path

import requests


def status_cli(*, config, create_client, extract_context_size, print_cli_header, print_section):
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
