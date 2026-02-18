"""Setup command logic for setup CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Protocol

from ai_stack.core.logging import emit_event


class _SetupResultLike(Protocol):
    missing_critical: list[str]
    clone_ok: bool
    build_ok: bool
    has_models: bool
    models_dir: Path


class _ConfigLike(Protocol):
    def print_summary(self) -> None: ...


class _SetupManagerLike(Protocol):
    def setup(self) -> _SetupResultLike: ...


def setup_cli(
    *,
    config: _ConfigLike,
    setup_manager_cls: Callable[[], _SetupManagerLike],
    print_cli_header: Callable[[str], None],
    print_divider: Callable[[], None],
    print_section: Callable[[str], None],
):
    """CLI for setup command."""
    emit_event("cli.setup.start")
    parser = argparse.ArgumentParser(description="AI Stack Setup")
    parser.parse_args()

    print_cli_header("AI Stack Setup")
    config.print_summary()

    manager = setup_manager_cls()
    result = manager.setup()

    if result.missing_critical:
        emit_event("cli.setup.failed", level="error", reason="missing_critical", missing=result.missing_critical)
        print_section("1. Checking dependencies...")
        print("✗ Missing critical dependencies:")
        for dep in result.missing_critical:
            print(f"  • {dep}")
        print("\nPlease install missing dependencies and try again.")
        sys.exit(1)

    if not result.clone_ok:
        emit_event("cli.setup.failed", level="error", reason="clone_failed")
        print_section("2. Setting up llama.cpp...")
        print("✗ Failed to set up llama.cpp")
        sys.exit(1)

    if not result.build_ok:
        emit_event("cli.setup.failed", level="error", reason="build_failed")
        print_section("3. Building llama.cpp...")
        print("✗ Build failed")
        sys.exit(1)

    print_divider()
    print("Setup complete!")
    print("=" * 60)

    print("\nNext steps:")
    if not result.has_models:
        print("1. Download models:")
        print(f"   mkdir -p {result.models_dir}")
        print("   # Download GGUF models from HuggingFace")
        print("   # Example: download-model TheBloke/Llama-2-7B-GGUF")
    else:
        print("1. Start server with a specific model:")
        print("   server-start <your-model.gguf>")

    print("\n2. Use the LLM client:")
    print("   from ai_stack.llm import create_client")
    print("   client = create_client()")
    print("   response = client.chat([{'role': 'user', 'content': 'Hello'}])")

    emit_event("cli.setup.complete", ok=True, has_models=result.has_models)
    sys.exit(0)


__all__ = ["setup_cli"]
