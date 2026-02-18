"""Dependency check command logic for setup CLI."""

from __future__ import annotations

import sys
from typing import Callable, Optional, Protocol


class _SetupManagerLike(Protocol):
    def check_dependencies(self) -> dict[str, bool]: ...


class _ExitWithErrorLike(Protocol):
    def __call__(self, *, message: str, detail: Optional[str] = None) -> None: ...


def check_deps_cli(
    *,
    setup_manager_cls: Callable[[], _SetupManagerLike],
    print_cli_header: Callable[[str], None],
    exit_with_error: _ExitWithErrorLike,
):
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
