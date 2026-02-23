"""Integration sync CLI commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_stack.core.errors import exit_with_error, exit_with_unexpected_error
from ai_stack.core.logging import emit_event
from ai_stack.integrations import sync_opencode_global_config


def sync_opencode_config_cli(argv=None):
    """Sync global OpenCode config from ai-stack runtime."""
    parser = argparse.ArgumentParser(
        description="Sync global OpenCode config from ai-stack runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sync-opencode-config
  sync-opencode-config --sync-tools --sync-agents --dry-run --print
  sync-opencode-config --global-path ~/.config/opencode/opencode.json
        """,
    )
    parser.add_argument(
        "--global-path",
        type=Path,
        help="Path to global opencode.json (default: ~/.config/opencode/opencode.json)",
    )
    parser.add_argument(
        "--sync-tools",
        action="store_true",
        help="Merge shared canonical tools into global OpenCode config",
    )
    parser.add_argument(
        "--sync-agents",
        action="store_true",
        help="Merge shared canonical agents into global OpenCode config",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and validate sync result without writing files",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print final JSON payload",
    )

    args = parser.parse_args(argv)

    try:
        emit_event(
            "cli.integrations.opencode_sync.start",
            global_path=str(args.global_path) if args.global_path else None,
            sync_tools=args.sync_tools,
            sync_agents=args.sync_agents,
            dry_run=args.dry_run,
        )

        result = sync_opencode_global_config(
            global_path=args.global_path,
            sync_tools=args.sync_tools,
            sync_agents=args.sync_agents,
            dry_run=args.dry_run,
        )

        if args.print:
            print(json.dumps(result.payload, indent=2))

        if result.warnings:
            print("\n⚠️  Sync warnings:")
            for warning in result.warnings:
                print(f"   - {warning}")

        if args.dry_run:
            print(f"\n🧪 Dry run complete (no file written): {result.path}")
        else:
            print(f"\n✅ Synced OpenCode config: {result.path}")

        emit_event(
            "cli.integrations.opencode_sync.complete",
            path=str(result.path),
            written=result.written,
            warning_count=len(result.warnings),
            validation_ok=result.validation_ok,
        )
        return 0

    except KeyboardInterrupt:
        emit_event("cli.integrations.opencode_sync.cancelled", level="info")
        print("\n❌ Sync cancelled")
        raise SystemExit(130)
    except ValueError as exc:
        emit_event("cli.integrations.opencode_sync.failed", level="error", error=str(exc))
        exit_with_error(message=str(exc))
    except Exception as exc:  # pragma: no cover - defensive wrapper boundary
        emit_event("cli.integrations.opencode_sync.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="OpenCode sync", exc=exc)


__all__ = ["sync_opencode_config_cli"]
