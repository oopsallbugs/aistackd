"""Local GGUF discovery and model selection stages."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from bootstrap.errors import StageError
from bootstrap.runner import StageContext
from bootstrap.stages.common import run_artifact_dir, write_json_artifact
from bootstrap.stages.llmfit import build_llmfit_env, ensure_hf_available

GGUF_DISCOVERY_ROOT_SUFFIXES = (
    (".cache", "huggingface"),
    (".cache", "llmfit"),
    (".cache", "llama.cpp"),
    (".llama.cpp", "models"),
)


@dataclass(frozen=True)
class GgufCandidate:
    path: Path
    size_bytes: int
    modified_at_epoch: float


def is_interactive_session(ctx: StageContext) -> bool:
    if bool(ctx.options.non_interactive):
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def resolve_local_model_path(path_value: str, *, source_label: str) -> Path:
    candidate = Path(path_value).expanduser().resolve()
    if not candidate.exists():
        raise StageError(code="model_install_failed", message=f"{source_label} does not exist: {candidate}", retryable=False)
    if not candidate.is_file():
        raise StageError(code="model_install_failed", message=f"{source_label} is not a file: {candidate}", retryable=False)
    if candidate.suffix.lower() != ".gguf":
        raise StageError(code="model_install_failed", message=f"{source_label} must point to a .gguf file: {candidate}", retryable=False)
    if not candidate.stat().st_size:
        raise StageError(code="model_install_failed", message=f"{source_label} is empty: {candidate}", retryable=False)
    return candidate


def format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024.0
    return f"{size_bytes}B"


def discover_gguf_candidates() -> list[GgufCandidate]:
    home = Path.home()
    roots = [home.joinpath(*parts) for parts in GGUF_DISCOVERY_ROOT_SUFFIXES]
    found: list[GgufCandidate] = []
    seen: set[Path] = set()

    for root in roots:
        if not root.exists():
            continue
        try:
            iterator = root.rglob("*.gguf")
        except OSError:
            continue
        for path in iterator:
            try:
                resolved = path.resolve()
                stat = resolved.stat()
            except OSError:
                continue
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            found.append(
                GgufCandidate(
                    path=resolved,
                    size_bytes=int(stat.st_size),
                    modified_at_epoch=float(stat.st_mtime),
                )
            )

    found.sort(key=lambda item: (-item.modified_at_epoch, item.path.name.lower(), str(item.path)))
    return found


def launch_llmfit_tui(llmfit_bin: Path, *, env: dict[str, str] | None = None) -> int:
    try:
        proc = subprocess.run([str(llmfit_bin)], check=False, env=env)
    except OSError as exc:
        raise StageError(code="model_install_failed", message=f"Failed to launch llmfit TUI: {exc}", retryable=False) from exc
    return int(proc.returncode)


def select_candidate_from_prompt(candidates: list[GgufCandidate]) -> GgufCandidate | None:
    print("[bootstrap.model.recommend] available local GGUF files:")
    for idx, candidate in enumerate(candidates, start=1):
        print(
            "[bootstrap.model.recommend]   {}. {} ({}) [{}]".format(
                idx,
                candidate.path.name,
                format_size(candidate.size_bytes),
                candidate.path.parent,
            )
        )

    while True:
        try:
            raw = input("[bootstrap.model.recommend] select model index (or 'q' to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not raw:
            continue
        if raw.lower() in {"q", "quit", "exit", "cancel"}:
            return None
        if not raw.isdigit():
            print(f"[bootstrap.model.recommend] invalid input '{raw}'; enter a number or 'q'.")
            continue
        index = int(raw)
        if index < 1 or index > len(candidates):
            print(f"[bootstrap.model.recommend] index {index} is out of range.")
            continue
        return candidates[index - 1]


def stage_model_recommend(ctx: StageContext) -> dict[str, Any]:
    llmfit_binary = ctx.checkpoint["artifacts"].get("llmfit_binary")
    if not llmfit_binary:
        raise StageError(code="llmfit_install_failed", message="llmfit binary artifact is missing")
    llmfit_bin = Path(str(llmfit_binary))

    checkpoint_artifacts = ctx.checkpoint.get("artifacts", {})
    preferred_model_path = (ctx.options.model_path or "").strip() or None
    existing_model_path = str(checkpoint_artifacts.get("default_model_path") or "").strip() or None
    chosen_model: str | None = None
    chosen_model_path: Path | None = None
    selected_model_file_name: str | None = None
    selection_source: str | None = None
    hf_binary: Path | None = None

    existing_source = str(checkpoint_artifacts.get("model_selection_source") or "").strip() or None
    existing_model_id = str(checkpoint_artifacts.get("default_model_id") or "").strip() or None
    if existing_source and existing_model_path:
        selection_source = existing_source
        chosen_model_path = resolve_local_model_path(existing_model_path, source_label="Previously selected model path")
        chosen_model = existing_model_id or chosen_model_path.stem
        selected_model_file_name = chosen_model_path.name

    if chosen_model is None:
        if preferred_model_path:
            chosen_model_path = resolve_local_model_path(preferred_model_path, source_label="--model-path")
            chosen_model = chosen_model_path.stem
            selection_source = "cli_model_path"
            selected_model_file_name = chosen_model_path.name
        elif is_interactive_session(ctx):
            llmfit_env = build_llmfit_env(ctx)
            hf_binary = ensure_hf_available(ctx, llmfit_env)
            print("[bootstrap.model.recommend] launching llmfit TUI for model selection")
            tui_exit_code = launch_llmfit_tui(llmfit_bin, env=llmfit_env)
            if tui_exit_code != 0:
                print(f"[bootstrap.model.recommend] llmfit TUI exited with code {tui_exit_code}; scanning GGUF inventory")
            candidates = discover_gguf_candidates()
            if not candidates:
                raise StageError(
                    code="model_install_failed",
                    message=(
                        "No GGUF files were discovered after llmfit TUI. "
                        "Bootstrap does not auto-download models. Re-run bootstrap and complete a download in llmfit TUI, "
                        "or pass --model-path <path-to-gguf>."
                    ),
                    retryable=False,
                )
            selected = select_candidate_from_prompt(candidates)
            if selected is None:
                raise StageError(
                    code="model_install_failed",
                    message=(
                        "Model selection cancelled. Re-run bootstrap and choose a model, "
                        "or pass --model-path <path-to-gguf>."
                    ),
                    retryable=False,
                )
            chosen_model_path = selected.path
            chosen_model = selected.path.stem
            selection_source = "tui_selection"
            selected_model_file_name = selected.path.name
        else:
            raise StageError(
                code="model_install_failed",
                message=(
                    "Non-interactive bootstrap requires --model-path <path-to-gguf>. "
                    "Automatic model downloads are disabled."
                ),
                retryable=False,
            )

    artifacts: dict[str, Any] = {
        "provider": "llama_cpp",
        "default_model_id": chosen_model,
        "model_selection_source": selection_source,
    }
    if hf_binary is not None:
        artifacts["hf_binary"] = str(hf_binary)
    if chosen_model_path is not None:
        artifacts["default_model_path"] = str(chosen_model_path)
        artifacts["selected_model_file_name"] = selected_model_file_name or chosen_model_path.name
    elif selected_model_file_name:
        artifacts["selected_model_file_name"] = selected_model_file_name

    return {
        "chosen_model": chosen_model,
        "chosen_model_path": str(chosen_model_path) if chosen_model_path else None,
        "raw_payload_path": None,
        "artifacts": artifacts,
    }


def stage_model_acquire(ctx: StageContext) -> dict[str, Any]:
    artifact_dir = run_artifact_dir(ctx)
    chosen_model_id = str(ctx.checkpoint["artifacts"].get("default_model_id") or "")
    chosen_model_path_value = str(ctx.checkpoint["artifacts"].get("default_model_path") or "")
    selection_source = str(ctx.checkpoint["artifacts"].get("model_selection_source") or "")

    if chosen_model_path_value:
        chosen_model_path = resolve_local_model_path(chosen_model_path_value, source_label="Selected default_model_path")
        resolved_model_id = chosen_model_id or chosen_model_path.stem
        selection_payload_path = artifact_dir / "selection.json"
        selection_payload = {
            "pre_downloaded": True,
            "model_id": resolved_model_id,
            "model_path": str(chosen_model_path),
            "selection_source": selection_source or "unknown",
            "selected_model_file_name": chosen_model_path.name,
        }
        write_json_artifact(selection_payload_path, selection_payload)
        print(f"[bootstrap.model.acquire] using pre-downloaded model {resolved_model_id} -> {chosen_model_path}")
        return {
            "model_path": str(chosen_model_path),
            "pre_downloaded": True,
            "raw_payload_path": str(selection_payload_path),
            "artifacts": {
                "default_model_id": resolved_model_id,
                "default_model_path": str(chosen_model_path),
                "selected_model_file_name": chosen_model_path.name,
                "llmfit_install_payload_path": str(selection_payload_path),
            },
        }

    detail = f" Selected model: {chosen_model_id}." if chosen_model_id else ""
    raise StageError(
        code="model_install_failed",
        message=(
            "A local GGUF model is required before acquisition."
            f"{detail} Bootstrap does not auto-download models. "
            "Re-run bootstrap and download/select a model in llmfit TUI, or pass --model-path <path-to-gguf>."
        ),
        retryable=False,
    )


__all__ = [
    "GGUF_DISCOVERY_ROOT_SUFFIXES",
    "GgufCandidate",
    "discover_gguf_candidates",
    "format_size",
    "is_interactive_session",
    "launch_llmfit_tui",
    "resolve_local_model_path",
    "select_candidate_from_prompt",
    "stage_model_acquire",
    "stage_model_recommend",
]
