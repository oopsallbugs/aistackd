"""Setup and maintenance CLI commands."""

from __future__ import annotations

import argparse
import shutil
import sys

from ai_stack.config import config
from ai_stack.setup import SetupManager


def setup_cli():
    """CLI for setup command"""
    parser = argparse.ArgumentParser(description="AI Stack Setup")
    parser.parse_args()

    print("=" * 60)
    print("AI Stack Setup")
    print("=" * 60)

    manager = SetupManager()
    success = manager.setup()

    sys.exit(0 if success else 1)


def check_deps_cli():
    """CLI for checking dependencies"""
    manager = SetupManager()
    deps = manager.check_dependencies()

    print("=" * 60)
    print("Dependency Check")
    print("=" * 60)

    all_good = True
    for dep, installed in deps.items():
        status = "✅" if installed else "❌"
        print(f"{status} {dep}")
        if not installed:
            all_good = False

    if all_good:
        print("\n✅ All dependencies satisfied!")
    else:
        print("\n❌ Some dependencies are missing")
        print("\nRun 'setup-stack' to install missing dependencies")

    sys.exit(0 if all_good else 1)


def uninstall_cli(argv=None):
    """CLI for uninstalling AI Stack"""
    parser = argparse.ArgumentParser(description="Uninstall AI Stack runtime artifacts")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args(argv)

    print("=" * 60)
    print("🧹 AI Stack Uninstall")
    print("=" * 60)
    print("\nThis will remove:")
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
        except Exception as exc:
            failed.append(f"Models: {exc}")

    if config.paths.llama_cpp_dir.exists():
        try:
            shutil.rmtree(config.paths.llama_cpp_dir)
            removed.append(f"llama.cpp: {config.paths.llama_cpp_dir}")
        except Exception as exc:
            failed.append(f"llama.cpp: {exc}")

    runtime_cache = config.paths.script_dir / ".ai_stack"
    if runtime_cache.exists():
        try:
            shutil.rmtree(runtime_cache)
            removed.append(f"Runtime cache: {runtime_cache}")
        except Exception as exc:
            failed.append(f"Runtime cache: {exc}")

    print("\n" + "=" * 60)
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


__all__ = ["setup_cli", "check_deps_cli", "uninstall_cli"]
