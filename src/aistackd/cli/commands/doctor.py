"""Doctor command scaffold and frontend-readiness checks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aistackd.frontends.catalog import SUPPORTED_FRONTENDS
from aistackd.frontends.sync import SyncOwnershipManifest
from aistackd.runtime.config import RuntimeConfig
from aistackd.runtime.remote import RemoteClientError, run_remote_smoke, validate_remote_runtime
from aistackd.skills.project_local import (
    PROJECT_LOCAL_SKILL_PROVENANCE_FILE_NAME,
    project_local_skill_roots,
)
from aistackd.state.layout import ProjectLayout
from aistackd.state.profiles import ProfileStore, ProfileStoreError

DEFAULT_READY_FRONTEND = "opencode"
DEFAULT_READY_TIMEOUT_SECONDS = 15


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``doctor`` command."""
    parser = subparsers.add_parser("doctor", help="inspect scaffold health and frontend readiness")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root to inspect",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    parser.set_defaults(handler=handle_scaffold)

    command_parsers = parser.add_subparsers(dest="doctor_command", metavar="doctor_command")

    scaffold_parser = command_parsers.add_parser("scaffold", help="inspect scaffold health and layout")
    scaffold_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root to inspect",
    )
    scaffold_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    scaffold_parser.set_defaults(handler=handle_scaffold)

    ready_parser = command_parsers.add_parser(
        "ready",
        help="check whether this machine is ready to use one synced frontend against the active host",
    )
    ready_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root to inspect",
    )
    ready_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    ready_parser.add_argument(
        "--frontend",
        choices=SUPPORTED_FRONTENDS,
        default=DEFAULT_READY_FRONTEND,
        help=f"frontend target to validate (default: {DEFAULT_READY_FRONTEND})",
    )
    ready_parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="skip the final /v1/responses smoke request",
    )
    ready_parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_READY_TIMEOUT_SECONDS,
        help=f"remote validation and smoke timeout in seconds (default: {DEFAULT_READY_TIMEOUT_SECONDS})",
    )
    ready_parser.set_defaults(handler=handle_ready)


def handle_scaffold(args: argparse.Namespace) -> int:
    """Handle the scaffold-focused doctor command."""
    layout = ProjectLayout.discover(args.project_root)
    if args.format == "json":
        print(json.dumps(layout.as_dict(), indent=2))
    else:
        print(layout.format_text())
    return 0


def handle_ready(args: argparse.Namespace) -> int:
    """Handle the frontend-readiness doctor command."""
    report = _build_frontend_readiness_report(
        args.project_root,
        args.frontend,
        timeout_seconds=args.timeout,
        skip_smoke=args.skip_smoke,
    )
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        _print_frontend_readiness_report(report)
    return 0 if report["ok"] else 1


def _build_frontend_readiness_report(
    project_root: Path,
    frontend: str,
    *,
    timeout_seconds: int,
    skip_smoke: bool,
) -> dict[str, object]:
    root = project_root.resolve()
    errors: list[str] = []
    sync_errors: list[str] = []
    local_checks: list[dict[str, object]] = []
    sync_checks: list[dict[str, object]] = []
    remote_validation_payload: dict[str, object] | None = None
    smoke_payload: dict[str, object] | None = None

    active_profile_name: str | None = None
    runtime_config: RuntimeConfig | None = None

    try:
        profile = ProfileStore(root).get_active_profile()
    except ProfileStoreError as exc:
        errors.append(str(exc))
        profile = None

    if profile is None:
        errors.append("no active profile is set")
    else:
        runtime_config = RuntimeConfig.for_client(profile, (frontend,))
        active_profile_name = runtime_config.active_profile
        api_key_present = bool(os.getenv(runtime_config.api_key_env, "").strip())
        local_checks.extend(
            (
                {
                    "label": "active_profile",
                    "ok": True,
                    "detail": runtime_config.active_profile,
                },
                {
                    "label": "api_key_env",
                    "ok": api_key_present,
                    "detail": runtime_config.api_key_env,
                },
            )
        )
        if not api_key_present:
            errors.append(f"api key environment variable '{runtime_config.api_key_env}' is not set or empty")

        ownership = SyncOwnershipManifest.load(root)
        if ownership is None:
            sync_errors.append("frontend sync has not been written yet; run 'aistackd sync --target %s --write'" % frontend)
        else:
            ownership_target = ownership.target_by_frontend(frontend)
            if ownership_target is None:
                sync_errors.append(
                    f"frontend '{frontend}' is not present in the ownership manifest; run 'aistackd sync --target {frontend} --write'"
                )
            else:
                missing_paths = [
                    managed_path.path
                    for managed_path in ownership_target.managed_paths
                    if not (root / managed_path.path).exists()
                ]
                sync_checks.append(
                    {
                        "label": "ownership_manifest",
                        "ok": True,
                        "detail": str((root / ".aistackd" / "sync" / "ownership_manifest.json").resolve()),
                    }
                )
                sync_checks.append(
                    {
                        "label": "managed_frontend_paths",
                        "ok": not missing_paths,
                        "detail": f"missing={len(missing_paths)}",
                    }
                )
                sync_checks.append(
                    {
                        "label": "project_local_skill_roots",
                        "ok": True,
                        "detail": ", ".join(
                            str((root / skill_root).resolve())
                            for skill_root in project_local_skill_roots(frontend)
                        ),
                    }
                )
                sync_checks.append(
                    {
                        "label": "project_local_skill_provenance_file",
                        "ok": True,
                        "detail": PROJECT_LOCAL_SKILL_PROVENANCE_FILE_NAME,
                    }
                )
                if missing_paths:
                    preview = ", ".join(missing_paths[:3])
                    suffix = "" if len(missing_paths) <= 3 else ", ..."
                    sync_errors.append(
                        f"frontend '{frontend}' has missing managed paths; re-run 'aistackd sync --target {frontend} --write' "
                        f"(missing: {preview}{suffix})"
                    )

    if runtime_config is not None and not errors and not sync_errors:
        try:
            validation = validate_remote_runtime(runtime_config, timeout_seconds=timeout_seconds)
            remote_validation_payload = validation.to_dict()
            if not validation.ok:
                errors.extend(validation.errors)
        except RemoteClientError as exc:
            errors.append(str(exc))

        if not skip_smoke and not errors:
            try:
                smoke_payload = run_remote_smoke(runtime_config, timeout_seconds=timeout_seconds)
            except RemoteClientError as exc:
                errors.append(str(exc))

    ok = not errors and not sync_errors
    return {
        "frontend": frontend,
        "active_profile": active_profile_name,
        "ok": ok,
        "project_root": str(root),
        "local_checks": local_checks,
        "sync_checks": sync_checks,
        "remote_validation": remote_validation_payload,
        "smoke": smoke_payload,
        "errors": [*sync_errors, *errors],
        "next_steps": _next_steps(frontend, runtime_config, sync_errors, errors, skip_smoke),
    }


def _next_steps(
    frontend: str,
    runtime_config: RuntimeConfig | None,
    sync_errors: list[str],
    errors: list[str],
    skip_smoke: bool,
) -> list[str]:
    steps: list[str] = []
    if runtime_config is None:
        steps.append("create and activate a profile with 'aistackd profiles add ... --activate'")
        return steps
    if not os.getenv(runtime_config.api_key_env, "").strip():
        steps.append(f"export {runtime_config.api_key_env}=<your-api-key>")
    if sync_errors:
        steps.append(f"run 'aistackd sync --target {frontend} --write'")
    if errors and not sync_errors:
        steps.append("ensure the host is started and reachable, then rerun 'aistackd client validate'")
    if not skip_smoke:
        steps.append(f"rerun 'aistackd doctor ready --frontend {frontend}' after changes")
    return steps


def _print_frontend_readiness_report(report: dict[str, object]) -> None:
    print("frontend readiness")
    print(f"frontend: {report.get('frontend')}")
    print(f"active_profile: {report.get('active_profile') or 'none'}")
    print(f"status: {'ok' if report.get('ok') else 'invalid'}")
    local_checks = report.get("local_checks")
    if isinstance(local_checks, list):
        for entry in local_checks:
            if not isinstance(entry, dict):
                continue
            print(
                f"local_check: {entry.get('label')} "
                f"status={'ok' if entry.get('ok') else 'missing'} detail={entry.get('detail')}"
            )
    sync_checks = report.get("sync_checks")
    if isinstance(sync_checks, list):
        for entry in sync_checks:
            if not isinstance(entry, dict):
                continue
            print(
                f"sync_check: {entry.get('label')} "
                f"status={'ok' if entry.get('ok') else 'invalid'} detail={entry.get('detail')}"
            )
    remote_validation = report.get("remote_validation")
    if isinstance(remote_validation, dict):
        print(f"remote_validation: {'ok' if remote_validation.get('ok') else 'invalid'}")
    smoke = report.get("smoke")
    if isinstance(smoke, dict):
        print(f"smoke: {'ok' if smoke.get('ok') else 'invalid'}")
        print(f"smoke_output_text: {smoke.get('output_text') or ''}")
    errors = report.get("errors")
    if isinstance(errors, list):
        for message in errors:
            print(f"error: {message}")
    next_steps = report.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        for step in next_steps:
            print(f"next_step: {step}")
