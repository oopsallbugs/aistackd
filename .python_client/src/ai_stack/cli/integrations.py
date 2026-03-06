"""Integration sync CLI commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_stack.core.errors import exit_with_error, exit_with_unexpected_error
from ai_stack.core.logging import emit_event
from ai_stack.integrations import sync_openhands_global_config, sync_opencode_global_config


def sync_opencode_config_cli(argv=None):
    """Sync global OpenCode config from ai-stack runtime."""
    parser = argparse.ArgumentParser(
        description="Sync global OpenCode config from ai-stack runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sync-opencode-config
  sync-opencode-config --sync-tools --sync-agents --sync-skills --dry-run --print
  sync-opencode-config --global-path ~/.config/opencode/opencode.json
        """,
    )
    parser.add_argument(
        "--global-path",
        type=Path,
        help="Path to global opencode.json (default: ~/.config/opencode/opencode.json)",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        help="Path to global OpenCode skills dir (default: ~/.config/opencode/skills)",
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
        "--sync-skills",
        action="store_true",
        help="Write shared canonical skills under ~/.config/opencode/skills/<name>/SKILL.md",
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
            skills_dir=str(args.skills_dir) if args.skills_dir else None,
            sync_tools=args.sync_tools,
            sync_agents=args.sync_agents,
            sync_skills=args.sync_skills,
            dry_run=args.dry_run,
        )

        result = sync_opencode_global_config(
            global_path=args.global_path,
            skills_dir=args.skills_dir,
            sync_tools=args.sync_tools,
            sync_agents=args.sync_agents,
            sync_skills=args.sync_skills,
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
            if result.skills_written:
                print(f"✅ Synced OpenCode skills: {len(result.skills_written)} file(s)")

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


def sync_openhands_config_cli(argv=None):
    """Sync global OpenHands config from ai-stack runtime."""
    parser = argparse.ArgumentParser(
        description="Sync global OpenHands config from ai-stack runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sync-openhands-config
  sync-openhands-config --sync-tools --sync-agents --sync-skills --dry-run --print
  sync-openhands-config --emit-mcp-json --mcp-json-path ~/.openhands/mcp.json
        """,
    )
    parser.add_argument(
        "--global-path",
        type=Path,
        help="Path to global OpenHands config.toml (default: ~/.openhands/config.toml)",
    )
    parser.add_argument(
        "--mcp-json-path",
        type=Path,
        help="Path to OpenHands mcp.json (default: ~/.openhands/mcp.json)",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        help="Path to OpenHands skills directory (default: ~/.openhands/skills)",
    )
    parser.add_argument(
        "--sync-tools",
        action="store_true",
        help="Merge shared canonical tools into OpenHands config",
    )
    parser.add_argument(
        "--sync-agents",
        action="store_true",
        help="Merge shared canonical agents into OpenHands config",
    )
    parser.add_argument(
        "--sync-skills",
        action="store_true",
        help="Write shared canonical skills into OpenHands skills directory",
    )
    parser.add_argument(
        "--emit-mcp-json",
        action="store_true",
        help="Also emit OpenHands mcp.json alongside config.toml sync",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and validate sync result without writing files",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print final payload summary as JSON",
    )

    args = parser.parse_args(argv)

    try:
        emit_event(
            "cli.integrations.openhands_sync.start",
            global_path=str(args.global_path) if args.global_path else None,
            mcp_json_path=str(args.mcp_json_path) if args.mcp_json_path else None,
            skills_dir=str(args.skills_dir) if args.skills_dir else None,
            sync_tools=args.sync_tools,
            sync_agents=args.sync_agents,
            sync_skills=args.sync_skills,
            emit_mcp_json=args.emit_mcp_json,
            dry_run=args.dry_run,
        )

        result = sync_openhands_global_config(
            global_path=args.global_path,
            mcp_json_path=args.mcp_json_path,
            skills_dir=args.skills_dir,
            sync_tools=args.sync_tools,
            sync_agents=args.sync_agents,
            sync_skills=args.sync_skills,
            emit_mcp_json=args.emit_mcp_json,
            dry_run=args.dry_run,
        )

        if args.print:
            print(json.dumps(result.config_payload, indent=2))
            if result.mcp_payload is not None:
                print("\nMCP JSON:")
                print(json.dumps(result.mcp_payload, indent=2))

        if result.warnings:
            print("\n⚠️  Sync warnings:")
            for warning in result.warnings:
                print(f"   - {warning}")

        if args.dry_run:
            print(f"\n🧪 Dry run complete (no file written): {result.config_path}")
        else:
            print(f"\n✅ Synced OpenHands config: {result.config_path}")
            if result.mcp_json_path is not None:
                print(f"✅ Synced OpenHands MCP JSON: {result.mcp_json_path}")
            if result.skills_written:
                print(f"✅ Synced OpenHands skills: {len(result.skills_written)} file(s)")

        emit_event(
            "cli.integrations.openhands_sync.complete",
            path=str(result.config_path),
            mcp_json_path=str(result.mcp_json_path) if result.mcp_json_path else None,
            skills_count=len(result.skills_written),
            written=result.written,
            warning_count=len(result.warnings),
            validation_ok=result.validation_ok,
        )
        return 0

    except KeyboardInterrupt:
        emit_event("cli.integrations.openhands_sync.cancelled", level="info")
        print("\n❌ Sync cancelled")
        raise SystemExit(130)
    except ValueError as exc:
        emit_event("cli.integrations.openhands_sync.failed", level="error", error=str(exc))
        exit_with_error(message=str(exc))
    except Exception as exc:  # pragma: no cover - defensive wrapper boundary
        emit_event("cli.integrations.openhands_sync.failed", level="error", error=str(exc))
        exit_with_unexpected_error(command="OpenHands sync", exc=exc)


__all__ = ["sync_opencode_config_cli", "sync_openhands_config_cli"]
