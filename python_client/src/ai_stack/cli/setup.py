"""Setup and maintenance CLI commands."""

from __future__ import annotations

from ai_stack.core.config import config
from ai_stack.core.errors import exit_with_error
from ai_stack.stack.manager import SetupManager
from ai_stack.cli.main import print_cli_header, print_divider, print_progress, print_section
from ai_stack.cli import setup_deps as setup_deps_cmd
from ai_stack.cli import setup_install as setup_install_cmd
from ai_stack.cli import setup_uninstall as setup_uninstall_cmd


def setup_cli():
    """CLI for setup command."""
    setup_install_cmd.setup_cli(
        config=config,
        setup_manager_cls=SetupManager,
        print_cli_header=print_cli_header,
        print_divider=print_divider,
        print_progress=print_progress,
        print_section=print_section,
    )


def check_deps_cli():
    """CLI for checking dependencies."""
    setup_deps_cmd.check_deps_cli(
        setup_manager_cls=SetupManager,
        print_cli_header=print_cli_header,
        exit_with_error=exit_with_error,
    )


def uninstall_cli(argv=None):
    """CLI for uninstalling AI Stack."""
    setup_uninstall_cmd.uninstall_cli(
        config=config,
        print_cli_header=print_cli_header,
        print_divider=print_divider,
        print_section=print_section,
        argv=argv,
    )


__all__ = ["setup_cli", "check_deps_cli", "uninstall_cli"]
