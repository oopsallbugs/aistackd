"""Dependency check command logic for setup CLI."""

from __future__ import annotations

import sys


def check_deps_cli(*, setup_manager_cls, print_cli_header, exit_with_error):
    """CLI for checking dependencies."""
    manager = setup_manager_cls()
    deps = manager.check_dependencies()

    print_cli_header("Dependency Check")

    all_good = True
    for dep, installed in deps.items():
        status = "✅" if installed else "❌"
        print(f"{status} {dep}")
        if not installed:
            all_good = False

    if all_good:
        print("\n✅ All dependencies satisfied!")
    else:
        exit_with_error(
            message="Some dependencies are missing",
            detail="Run 'setup-stack' to install missing dependencies",
        )

    sys.exit(0)


__all__ = ["check_deps_cli"]
