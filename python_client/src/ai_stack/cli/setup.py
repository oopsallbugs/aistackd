"""Setup and maintenance CLI commands."""

from __future__ import annotations

from ai_stack.core.config import config
from ai_stack.core.errors import exit_with_error, exit_with_unexpected_error
from ai_stack.core.logging import emit_event
from ai_stack.stack.manager import SetupManager
from ai_stack.cli.main import print_cli_header, print_divider, print_progress, print_section
from ai_stack.cli import setup_deps as setup_deps_cmd
from ai_stack.cli import setup_install as setup_install_cmd
from ai_stack.cli import setup_uninstall as setup_uninstall_cmd


def setup_cli():
    """CLI for setup command."""
    try:
        setup_install_cmd.setup_cli(
            config=config,
            setup_manager_cls=SetupManager,
            print_cli_header=print_cli_header,
            print_divider=print_divider,
            print_progress=print_progress,
            print_section=print_section,
        )
    except Exception as exc:
        emit_event("cli.setup.wrapper.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="Setup", exc=exc)


def check_deps_cli():
    """CLI for checking dependencies."""
    try:
        setup_deps_cmd.check_deps_cli(
            setup_manager_cls=SetupManager,
            print_cli_header=print_cli_header,
            exit_with_error=exit_with_error,
        )
    except Exception as exc:
        emit_event("cli.check_deps.wrapper.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="Dependency check", exc=exc)


def uninstall_cli(argv=None):
    """CLI for uninstalling AI Stack."""
    try:
        setup_uninstall_cmd.uninstall_cli(
            config=config,
            print_cli_header=print_cli_header,
            print_divider=print_divider,
            print_section=print_section,
            argv=argv,
        )
    except Exception as exc:
        emit_event("cli.uninstall.wrapper.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="Uninstall", exc=exc)


__all__ = ["setup_cli", "check_deps_cli", "uninstall_cli"]
