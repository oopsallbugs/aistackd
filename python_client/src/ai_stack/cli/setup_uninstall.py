"""Uninstall command logic for setup CLI."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Callable, Protocol


class _PathsLike(Protocol):
    models_dir: Path
    llama_cpp_dir: Path
    project_root: Path


class _ConfigLike(Protocol):
    paths: _PathsLike


def uninstall_cli(
    *,
    config: _ConfigLike,
    print_cli_header: Callable[[str], None],
    print_divider: Callable[[], None],
    print_section: Callable[[str], None],
    argv=None,
):
    """CLI for uninstalling AI Stack."""
    parser = argparse.ArgumentParser(description="Uninstall AI Stack runtime artifacts")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Remove all runtime artifacts (default when no specific flags are provided)",
    )
    parser.add_argument(
        "--models",
        action="store_true",
        help="Remove downloaded models directory",
    )
    parser.add_argument(
        "--llama",
        action="store_true",
        help="Remove llama.cpp directory",
    )
    parser.add_argument(
        "--runtime-cache",
        action="store_true",
        help="Remove runtime cache directory (.ai_stack)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args(argv)

    selected_any = args.models or args.llama or args.runtime_cache
    remove_models = args.models or (args.all or not selected_any)
    remove_llama = args.llama or (args.all or not selected_any)
    remove_runtime_cache = args.runtime_cache or (args.all or not selected_any)

    selected_labels = []
    if remove_llama:
        selected_labels.append("llama.cpp build directory")
    if remove_models:
        selected_labels.append("All downloaded models")
    if remove_runtime_cache:
        selected_labels.append("Runtime cache (.ai_stack)")

    print_cli_header("🧹 AI Stack Uninstall")
    print_section("This will remove:")
    for label in selected_labels:
        print(f"  • {label}")
    print()

    if not args.yes:
        try:
            response = input("Are you sure you want to uninstall? (y/N): ")
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Uninstall cancelled")
            return
        if response.lower() != "y":
            print("❌ Uninstall cancelled")
            return

    removed = []
    failed = []

    if remove_models and config.paths.models_dir.exists():
        try:
            shutil.rmtree(config.paths.models_dir)
            removed.append(f"Models: {config.paths.models_dir}")
        except OSError as exc:
            failed.append(f"Models: {exc}")

    if remove_llama and config.paths.llama_cpp_dir.exists():
        try:
            shutil.rmtree(config.paths.llama_cpp_dir)
            removed.append(f"llama.cpp: {config.paths.llama_cpp_dir}")
        except OSError as exc:
            failed.append(f"llama.cpp: {exc}")

    runtime_cache = config.paths.project_root / ".ai_stack"
    if remove_runtime_cache and runtime_cache.exists():
        try:
            shutil.rmtree(runtime_cache)
            removed.append(f"Runtime cache: {runtime_cache}")
        except OSError as exc:
            failed.append(f"Runtime cache: {exc}")

    print_divider()
    if removed:
        print("✅ Removed:")
        for item in removed:
            print(f"  • {item}")

    if failed:
        print("\n❌ Failed to remove:")
        for item in failed:
            print(f"  • {item}")

    if not removed and not failed:
        print("✅ Nothing to remove - AI Stack not installed")

    print("\n📝 Note: To completely remove the package itself:")
    print("  pip uninstall ai-stack")


__all__ = ["uninstall_cli"]
