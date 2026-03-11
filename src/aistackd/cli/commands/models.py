"""Models command implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aistackd.models.acquisition import (
    DEFAULT_HUGGING_FACE_CLI,
    DEFAULT_LLMFIT_IMPORT_METHOD,
    ManagedGgufImportReport,
    ModelAcquisitionError,
    acquire_managed_model_artifact,
    diff_gguf_snapshots,
    import_managed_gguf_candidates,
    iter_llmfit_watch_roots,
    parse_hugging_face_url,
    snapshot_gguf_roots,
)
from aistackd.models.llmfit import LlmfitCommandError, launch_llmfit_browser
from aistackd.models.selection import derive_model_name_from_artifact_name, infer_quantization_from_artifact_name
from aistackd.models.sources import (
    FALLBACK_MODEL_SOURCE,
    LOCAL_MODEL_SOURCE,
    PRIMARY_MODEL_SOURCE,
    SUPPORTED_MODEL_SOURCES,
    ModelSourceError,
    SourceModel,
    local_source_model,
    recommend_models,
    resolve_source_model,
    search_models,
)
from aistackd.runtime.bootstrap import BootstrapError, resolve_tool_binary
from aistackd.runtime.hardware import LLMFIT_BINARY_NAME
from aistackd.state.host import HostStateError, HostStateStore, InstalledModelNotFoundError
from aistackd.state.profiles import Profile, ProfileStore, ProfileStoreError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``models`` command."""
    parser = subparsers.add_parser("models", help="inspect profile targets and host model state")
    _add_common_arguments(parser)
    parser.set_defaults(handler=handle_show)

    command_parsers = parser.add_subparsers(dest="models_command", metavar="models_command")

    list_parser = command_parsers.add_parser("list", help="list configured profile models")
    _add_common_arguments(list_parser)
    list_parser.set_defaults(handler=handle_list)

    show_parser = command_parsers.add_parser("show", help="show the target model for one profile")
    _add_common_arguments(show_parser)
    show_parser.add_argument("name", nargs="?", help="profile name to inspect; defaults to the active profile")
    show_parser.set_defaults(handler=handle_show)

    set_parser = command_parsers.add_parser("set", help="set the target model for a profile")
    _add_common_arguments(set_parser)
    set_parser.add_argument("model", help="model identifier to store on the profile")
    set_parser.add_argument(
        "--profile",
        dest="profile_name",
        help="profile name to update; defaults to the active profile",
    )
    set_parser.set_defaults(handler=handle_set)

    search_parser = command_parsers.add_parser("search", help="search the live llmfit model catalog")
    _add_common_arguments(search_parser)
    _add_llmfit_arguments(search_parser)
    search_parser.add_argument("query", nargs="?", help="optional query string")
    search_parser.set_defaults(handler=handle_search)

    recommend_parser = command_parsers.add_parser("recommend", help="show llmfit recommendations")
    _add_common_arguments(recommend_parser)
    _add_llmfit_arguments(recommend_parser)
    recommend_parser.set_defaults(handler=handle_recommend)

    browse_parser = command_parsers.add_parser("browse", help="launch the native llmfit TUI and import new GGUFs")
    _add_common_arguments(browse_parser)
    _add_llmfit_arguments(browse_parser)
    _add_watch_root_arguments(browse_parser)
    browse_parser.set_defaults(handler=handle_browse)

    import_parser = command_parsers.add_parser("import-llmfit", help="import GGUFs from llmfit watch roots")
    _add_common_arguments(import_parser)
    _add_watch_root_arguments(import_parser)
    import_parser.set_defaults(handler=handle_import_llmfit)

    installed_parser = command_parsers.add_parser("installed", help="list installed host models")
    _add_common_arguments(installed_parser)
    installed_parser.set_defaults(handler=handle_installed)

    install_parser = command_parsers.add_parser("install", help="install a model into host state")
    _add_common_arguments(install_parser)
    _add_llmfit_arguments(install_parser)
    install_parser.add_argument("model", nargs="?", help="model identifier to install")
    install_parser.add_argument("--source", choices=SUPPORTED_MODEL_SOURCES, help="force one model source")
    install_parser.add_argument("--gguf-path", type=Path, help="explicit path to a local GGUF to import")
    install_parser.add_argument(
        "--local-root",
        dest="local_roots",
        action="append",
        type=Path,
        default=[],
        help="additional local root to scan for matching GGUF files",
    )
    install_parser.add_argument("--hf-url", help="Hugging Face model/file URL to use for fallback acquisition")
    install_parser.add_argument("--hf-repo", help="Hugging Face repo to use for fallback acquisition")
    install_parser.add_argument("--hf-file", help="GGUF filename to use for Hugging Face fallback")
    install_parser.add_argument("--quant", help="preferred llmfit quantization for direct downloads")
    install_parser.add_argument("--budget", dest="budget_gb", type=float, help="llmfit memory budget in GB")
    install_parser.add_argument(
        "--hf-cli",
        default=DEFAULT_HUGGING_FACE_CLI,
        help=f"Hugging Face CLI executable used for fallback downloads (default: {DEFAULT_HUGGING_FACE_CLI})",
    )
    install_parser.add_argument("--activate", action="store_true", help="activate the model after installing it")
    install_parser.set_defaults(handler=handle_install)

    activate_parser = command_parsers.add_parser("activate", help="activate an installed host model")
    _add_common_arguments(activate_parser)
    activate_parser.add_argument("model", help="installed model identifier to activate")
    activate_parser.set_defaults(handler=handle_activate)


def handle_list(args: argparse.Namespace) -> int:
    """List target models for all configured profiles."""
    try:
        store = ProfileStore(args.project_root)
        profiles = store.list_profiles()
        active_profile_name = store.get_active_profile_name()
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        payload = {
            "profiles": [_profile_model_payload(profile, active_profile_name) for profile in profiles],
            "active_profile": active_profile_name,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not profiles:
        print("no profiles configured")
        return 0

    print(f"profile_models: {len(profiles)}")
    for profile in profiles:
        active_marker = "*" if profile.name == active_profile_name else " "
        print(f"{active_marker} {profile.name}: {profile.model}")
    return 0


def handle_show(args: argparse.Namespace) -> int:
    """Show the target model for one profile."""
    try:
        store = ProfileStore(args.project_root)
        active_profile_name = store.get_active_profile_name()
        profile_name = getattr(args, "name", None)
        profile = store.load_profile(profile_name) if profile_name else store.get_active_profile()
        if profile is None:
            return _exit_with_error("no active profile is set")
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    payload = _profile_model_payload(profile, active_profile_name)
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"profile: {profile.name}")
    print(f"model: {profile.model}")
    print(f"active: {'yes' if payload['active'] else 'no'}")
    print(f"base_url: {profile.base_url}")
    return 0


def handle_set(args: argparse.Namespace) -> int:
    """Update the target model for one profile."""
    try:
        store = ProfileStore(args.project_root)
        profile_name = args.profile_name or store.get_active_profile_name()
        if profile_name is None:
            return _exit_with_error("no active profile is set")
        existing_profile = store.load_profile(profile_name)
        updated_profile = existing_profile.with_model(args.model)
        store.save_profile(updated_profile)
        active_profile_name = store.get_active_profile_name()
    except ProfileStoreError as exc:
        return _exit_with_error(str(exc))

    payload = _profile_model_payload(updated_profile, active_profile_name)
    if args.format == "json":
        print(json.dumps({"action": "updated", "profile": payload}, indent=2))
        return 0

    print(f"updated model for profile '{updated_profile.name}'")
    print(f"model: {updated_profile.model}")
    return 0


def handle_search(args: argparse.Namespace) -> int:
    """Search the live llmfit catalog."""
    try:
        models = search_models(
            args.query,
            llmfit_binary=_resolve_llmfit_binary(args.project_root, args.llmfit_binary),
        )
    except (ModelSourceError, ValueError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(
            json.dumps(
                {
                    "query": args.query,
                    "source": PRIMARY_MODEL_SOURCE,
                    "models": [model.as_dict() for model in models],
                },
                indent=2,
            )
        )
        return 0

    print(f"available_models: {len(models)}")
    for model in models:
        print(_format_source_model_line(model))
    return 0


def handle_recommend(args: argparse.Namespace) -> int:
    """Show policy-ranked llmfit recommendations."""
    try:
        models = recommend_models(llmfit_binary=_resolve_llmfit_binary(args.project_root, args.llmfit_binary))
    except (ModelSourceError, ValueError) as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        print(
            json.dumps(
                {
                    "source": PRIMARY_MODEL_SOURCE,
                    "models": [model.as_dict() for model in models],
                },
                indent=2,
            )
        )
        return 0

    print(f"recommended_models: {len(models)}")
    for model in models:
        print(_format_source_model_line(model))
    return 0


def handle_browse(args: argparse.Namespace) -> int:
    """Launch the native llmfit browser and import new or changed GGUFs."""
    watch_roots = _watch_roots_from_args(args)
    before = snapshot_gguf_roots(watch_roots)

    try:
        command, llmfit_exit_code = launch_llmfit_browser(
            llmfit_binary=_resolve_llmfit_binary(args.project_root, args.llmfit_binary)
        )
    except LlmfitCommandError as exc:
        return _exit_with_error(str(exc))

    report = ManagedGgufImportReport(entries=())
    exit_code = llmfit_exit_code
    if llmfit_exit_code == 0:
        after = snapshot_gguf_roots(watch_roots)
        changed_paths = diff_gguf_snapshots(before, after)
        report = import_managed_gguf_candidates(
            args.project_root,
            changed_paths,
            source_name=PRIMARY_MODEL_SOURCE,
            acquisition_method="llmfit_browse_import",
        )
        if report.failed_count:
            exit_code = 1

    payload = {
        "action": "browse",
        "llmfit_command": list(command),
        "llmfit_exit_code": llmfit_exit_code,
        "watch_roots": [str(path) for path in watch_roots],
        "imports": report.to_dict(),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return exit_code

    print(f"llmfit_exit_code: {llmfit_exit_code}")
    print(f"watch_roots: {', '.join(str(path) for path in watch_roots)}")
    if llmfit_exit_code != 0:
        print("imports_skipped: llmfit exited nonzero; no managed imports were attempted")
        return exit_code
    _print_import_report(report)
    return exit_code


def handle_import_llmfit(args: argparse.Namespace) -> int:
    """Import all currently visible llmfit GGUFs from watched roots."""
    watch_roots = _watch_roots_from_args(args)
    snapshot = snapshot_gguf_roots(watch_roots)
    report = import_managed_gguf_candidates(
        args.project_root,
        tuple(Path(path) for path in sorted(snapshot)),
        source_name=PRIMARY_MODEL_SOURCE,
        acquisition_method=DEFAULT_LLMFIT_IMPORT_METHOD,
    )

    payload = {
        "action": "imported",
        "watch_roots": [str(path) for path in watch_roots],
        "imports": report.to_dict(),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 1 if report.failed_count else 0

    print(f"watch_roots: {', '.join(str(path) for path in watch_roots)}")
    _print_import_report(report)
    return 1 if report.failed_count else 0


def handle_installed(args: argparse.Namespace) -> int:
    """List installed host models."""
    try:
        store = HostStateStore(args.project_root)
        runtime_state = store.load_runtime_state()
    except HostStateError as exc:
        return _exit_with_error(str(exc))

    if args.format == "json":
        payload = {
            "active_model": runtime_state.active_model,
            "models": [record.as_dict() for record in runtime_state.installed_models],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"installed_models: {len(runtime_state.installed_models)}")
    for record in runtime_state.installed_models:
        active_marker = "*" if record.model == runtime_state.active_model else " "
        print(
            f"{active_marker} {record.model}: source={record.source} "
            f"method={record.acquisition_method} status={record.status} installed_at={record.installed_at}"
        )
    return 0


def handle_install(args: argparse.Namespace) -> int:
    """Install one model into host state."""
    try:
        if args.budget_gb is not None and args.budget_gb <= 0:
            return _exit_with_error("--budget must be positive when provided")
        hf_repo, hf_file = _resolve_hugging_face_inputs(args)
        if bool(hf_repo) != bool(hf_file):
            return _exit_with_error("Hugging Face fallback requires both --hf-repo and --hf-file")
        requested_model_name = _resolve_requested_model_name(args.model, gguf_path=args.gguf_path, hf_file=hf_file)
        source_model = _resolve_install_source_model(
            requested_model_name,
            source=args.source,
            gguf_path=args.gguf_path,
            llmfit_binary=_resolve_llmfit_binary(args.project_root, args.llmfit_binary),
            prefer_hugging_face=hf_repo is not None,
        )
        acquisition = acquire_managed_model_artifact(
            args.project_root,
            source_model,
            explicit_gguf_path=args.gguf_path,
            local_roots=tuple(args.local_roots),
            preferred_source=args.source,
            hugging_face_repo=hf_repo,
            hugging_face_file=hf_file,
            hugging_face_cli=_resolve_hf_binary(args.project_root, args.hf_cli),
            llmfit_binary=_resolve_llmfit_binary(args.project_root, args.llmfit_binary),
            llmfit_quant=args.quant,
            llmfit_budget_gb=args.budget_gb,
        )
        store = HostStateStore(args.project_root)
        record, created = store.install_model(
            source_model,
            acquisition_source=acquisition.source,
            acquisition_method=acquisition.acquisition_method,
            artifact_path=Path(acquisition.artifact_path),
            size_bytes=acquisition.size_bytes,
            sha256=acquisition.sha256,
        )
        runtime_state = store.activate_model(record.model) if args.activate else store.load_runtime_state()
    except (HostStateError, InstalledModelNotFoundError, ModelAcquisitionError, ModelSourceError, ValueError) as exc:
        return _exit_with_error(str(exc))

    action = "installed" if created else "updated"
    payload = {
        "action": action,
        "model": record.as_dict(),
        "active_model": runtime_state.active_model,
        "activation_state": runtime_state.activation_state,
        "acquisition": acquisition.to_dict(),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"{action} model '{record.model}' from {record.source}")
    print(f"acquisition_method: {record.acquisition_method}")
    print(f"artifact_path: {record.artifact_path}")
    print(f"size_bytes: {record.size_bytes}")
    for attempt in acquisition.attempts:
        status = "ok" if attempt.ok else "failed"
        print(f"attempt: {attempt.provider}/{attempt.strategy} status={status} detail={attempt.detail}")
    if args.activate:
        print(f"active_model: {runtime_state.active_model}")
    return 0


def handle_activate(args: argparse.Namespace) -> int:
    """Activate one installed host model."""
    try:
        runtime_state = HostStateStore(args.project_root).activate_model(args.model)
    except (HostStateError, InstalledModelNotFoundError) as exc:
        return _exit_with_error(str(exc))

    payload = runtime_state.to_dict()
    if args.format == "json":
        print(json.dumps({"action": "activated", "runtime": payload}, indent=2))
        return 0

    print(f"activated model '{args.model}'")
    print(f"active_source: {runtime_state.active_source}")
    print(f"activation_state: {runtime_state.activation_state}")
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared CLI arguments."""
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root containing the .aistackd state directory",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )


def _add_llmfit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--llmfit-binary",
        default=LLMFIT_BINARY_NAME,
        help=f"llmfit executable to use for discovery or browse commands (default: {LLMFIT_BINARY_NAME})",
    )


def _add_watch_root_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--watch-root",
        dest="watch_roots",
        action="append",
        type=Path,
        default=[],
        help="additional root to watch for llmfit-downloaded GGUF files",
    )


def _profile_model_payload(profile: Profile, active_profile_name: str | None) -> dict[str, object]:
    """Build a stable JSON payload for one profile model."""
    return {
        "profile": profile.name,
        "model": profile.model,
        "active": profile.name == active_profile_name,
        "base_url": profile.base_url,
        "schema_version": profile.schema_version,
    }


def _format_source_model_line(model: SourceModel) -> str:
    parts = [
        f"{model.name}",
        f"source={model.source}",
        f"context={model.context_window}",
        f"quantization={model.quantization}",
    ]
    if model.recommended_rank is not None:
        parts.append(f"recommended_rank={model.recommended_rank}")
    parts.append(f"summary={model.summary}")
    return " ".join(parts)


def _watch_roots_from_args(args: argparse.Namespace) -> tuple[Path, ...]:
    return iter_llmfit_watch_roots(tuple(args.watch_roots))


def _print_import_report(report: ManagedGgufImportReport) -> None:
    print(f"imported: {report.imported_count}")
    print(f"skipped: {report.skipped_count}")
    print(f"failed: {report.failed_count}")
    for entry in report.entries:
        print(f"{entry.action}: model={entry.model or '<unknown>'} source_path={entry.source_path} detail={entry.detail}")


def _resolve_hugging_face_inputs(args: argparse.Namespace) -> tuple[str | None, str | None]:
    if args.hf_url and (args.hf_repo or args.hf_file):
        raise ModelAcquisitionError("use either --hf-url or the --hf-repo/--hf-file pair, not both")
    if args.hf_url:
        reference = parse_hugging_face_url(args.hf_url)
        if reference.filename is None:
            raise ModelAcquisitionError(
                "Hugging Face URL does not identify a GGUF file; provide --hf-file or a file-specific URL"
            )
        return reference.repo, reference.filename
    return args.hf_repo, args.hf_file


def _resolve_requested_model_name(
    model_name: str | None,
    *,
    gguf_path: Path | None,
    hf_file: str | None,
) -> str:
    if model_name is not None:
        return model_name
    if gguf_path is not None:
        return derive_model_name_from_artifact_name(gguf_path.name)
    if hf_file is not None:
        return derive_model_name_from_artifact_name(Path(hf_file).name)
    raise ModelAcquisitionError("model is required unless --gguf-path or --hf-url provides a GGUF filename")


def _resolve_install_source_model(
    model_name: str,
    *,
    source: str | None,
    gguf_path: Path | None,
    llmfit_binary: str,
    prefer_hugging_face: bool,
) -> SourceModel:
    if prefer_hugging_face:
        quantization = infer_quantization_from_artifact_name(model_name)
        return local_source_model(
            model_name,
            source=FALLBACK_MODEL_SOURCE,
            summary="Hugging Face GGUF install",
            quantization=quantization,
            tags=("hugging-face", "download"),
        )

    match: SourceModel | None = None
    if source in (None, PRIMARY_MODEL_SOURCE):
        try:
            match = resolve_source_model(model_name, source=PRIMARY_MODEL_SOURCE, llmfit_binary=llmfit_binary)
        except ModelSourceError:
            match = None
    if match is not None:
        return match

    quantization = infer_quantization_from_artifact_name(gguf_path.name if gguf_path is not None else model_name)
    synthetic_source = source or LOCAL_MODEL_SOURCE
    return local_source_model(model_name, source=synthetic_source, quantization=quantization)


def _exit_with_error(message: str) -> int:
    """Print an error message and return a failing exit code."""
    print(message, file=sys.stderr)
    return 1


def _resolve_llmfit_binary(project_root: Path, requested_binary: str) -> str:
    try:
        return resolve_tool_binary(project_root, "llmfit", requested=requested_binary)
    except BootstrapError:
        return requested_binary


def _resolve_hf_binary(project_root: Path, requested_binary: str) -> str:
    try:
        return resolve_tool_binary(project_root, "hf", requested=requested_binary)
    except BootstrapError:
        return requested_binary
