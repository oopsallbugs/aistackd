"""Uninstall command logic for setup CLI."""

from __future__ import annotations

import argparse
import shutil


def uninstall_cli(*, config, print_cli_header, print_divider, print_section, argv=None):
    """CLI for uninstalling AI Stack."""
    parser = argparse.ArgumentParser(description="Uninstall AI Stack runtime artifacts")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args(argv)

    print_cli_header("🧹 AI Stack Uninstall")
    print_section("This will remove:")
    print("  • llama.cpp build directory")
    print("  • All downloaded models")
    print("  • Runtime cache (.ai_stack)")
    print()

    if not args.yes:
        response = input("Are you sure you want to uninstall? (y/N): ")
        if response.lower() != "y":
            print("❌ Uninstall cancelled")
            return

    removed = []
    failed = []

    if config.paths.models_dir.exists():
        try:
            shutil.rmtree(config.paths.models_dir)
            removed.append(f"Models: {config.paths.models_dir}")
        except OSError as exc:
            failed.append(f"Models: {exc}")

    if config.paths.llama_cpp_dir.exists():
        try:
            shutil.rmtree(config.paths.llama_cpp_dir)
            removed.append(f"llama.cpp: {config.paths.llama_cpp_dir}")
        except OSError as exc:
            failed.append(f"llama.cpp: {exc}")

    runtime_cache = config.paths.project_root / ".ai_stack"
    if runtime_cache.exists():
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
