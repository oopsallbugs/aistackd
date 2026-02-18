"""Model download CLI commands."""

from __future__ import annotations

import argparse
import sys

from huggingface_hub.errors import HFValidationError

from ai_stack.cli.main import print_bullet_list, print_progress, print_section
from ai_stack.core.errors import exit_with_error
from ai_stack.core.logging import emit_event
from ai_stack.stack import hf_downloads
from ai_stack.stack.manager import SetupManager


def _print_cache_event(manager: SetupManager, cache_event: str | None, repo_id: str, revision: str = "main") -> None:
    message = manager.format_cache_event(cache_event, repo_id, revision)
    if message:
        print(message)


def _print_hf_file_list(result: hf_downloads.HfFileListResult) -> None:
    print_section(f"📦 {result.repo_id}")
    if result.pipeline_tag:
        print(f"   Type: {result.pipeline_tag}")
    if result.tags:
        tags = ", ".join(result.tags[:8])
        if len(result.tags) > 8:
            tags += "..."
        print(f"   Tags: {tags}")
    if result.sha:
        print(f"   SHA: {result.sha[:12]}")

    if result.gguf_files:
        print_section("📋 Available GGUF files:")
        rows = []
        for index, file in enumerate(result.gguf_files[:10], 1):
            size_str = f" ({file.size // 1024 // 1024} MB)" if file.size else ""
            rows.append(f"{index}. {file.path}{size_str}")
        print_bullet_list(rows, prefix="  ")
        if len(result.gguf_files) > 10:
            print(f"  ... and {len(result.gguf_files) - 10} more")
    else:
        print_section("❌ No GGUF files found.")

    if result.mmproj_files:
        print_section("🖼️  MMproj files available:")
        rows = []
        for file in result.mmproj_files:
            size_str = f" ({file.size // 1024 // 1024} MB)" if file.size else ""
            rows.append(f"{file.path}{size_str}")
        print_bullet_list(rows)


def _print_download_result(result: hf_downloads.HfDownloadResult) -> None:
    if not result.success:
        detail = result.error or "Download failed"
        exit_with_error(message=detail, detail="Tip: use --list to see available files.")

    if result.selected_model_file:
        print(f"\n📝 Auto-selected: {result.selected_model_file}")
    if result.quant_preference:
        print(f"   Quant preference: {result.quant_preference}")
    if result.mmproj_path:
        print(f"🖼️  Downloading MMproj: {result.mmproj_path.name}")

    print_section("✅ Download complete!")
    print(f"   Model: {result.model_path.name}")
    if result.mmproj_path:
        print(f"   MMproj: {result.mmproj_path.name}")

    print("\n📋 To start the server:")
    print(f"   server-start {result.model_path.name}")


def download_model_cli():
    """CLI for downloading models from HuggingFace"""
    emit_event("cli.download.start")
    parser = argparse.ArgumentParser(
        description="Download a model from HuggingFace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  download-model TheBloke/Llama-2-7B-GGUF           # Download default model
  download-model Qwen/Qwen2.5-7B-Instruct-GGUF -f qwen2.5-7b-instruct-q4_k_m.gguf
  download-model Qwen/Qwen2.5-7B-Instruct-GGUF --list  # List available files
  download-model Qwen/Qwen2.5-7B-Instruct-GGUF --mmproj  # Auto-select MMproj
        """,
    )
    parser.add_argument("repo", help="HuggingFace repo ID (e.g., 'TheBloke/Llama-2-7B-GGUF')")
    parser.add_argument("-f", "--file", help="Specific filename to download (default: auto-select)")
    parser.add_argument("--quant", help="Preferred quant for auto-selection (e.g., Q5_K_M)")
    parser.add_argument("--mmproj", action="store_true", help="Also download MMproj file if available")
    parser.add_argument("--list", "-l", action="store_true", help="List available files and exit")
    parser.add_argument(
        "--cache-diagnostics",
        action="store_true",
        help="Show HF snapshot cache diagnostics for this command run",
    )

    args = parser.parse_args()
    manager = SetupManager()

    if args.list:
        try:
            print_progress(1, 2, f"Fetching snapshot metadata for {args.repo}")
            result = manager.list_huggingface_files(args.repo)
            _print_cache_event(manager, result.cache_event, result.repo_id)
            print_progress(2, 2, "Rendering available file list")
            _print_hf_file_list(result)
            emit_event(
                "cli.download.list.complete",
                repo_id=result.repo_id,
                gguf_count=len(result.gguf_files),
                mmproj_count=len(result.mmproj_files),
            )
        except (HFValidationError, ValueError) as exc:
            emit_event("cli.download.list.failed", level="error", error=str(exc))
            exit_with_error(
                message=f"Invalid HuggingFace repo input: {exc}",
                detail="Use 'namespace/repo' or a full model URL on huggingface.co",
            )
        if args.cache_diagnostics:
            manager.print_cache_diagnostics()
        return

    try:
        print_progress(1, 3, f"Fetching snapshot metadata for {args.repo}")
        result = manager.download_from_huggingface(
            repo_id=args.repo,
            filename=args.file,
            download_mmproj=args.mmproj,
            quant_preference=args.quant,
        )
        _print_cache_event(manager, result.cache_event, result.repo_id)
        print_progress(2, 3, "Resolving and downloading selected files")
        _print_download_result(result)
        print_progress(3, 3, "Completed download workflow")
        emit_event(
            "cli.download.complete",
            repo_id=result.repo_id,
            ok=result.success,
            selected_model_file=result.selected_model_file,
        )
    except (HFValidationError, ValueError) as exc:
        emit_event("cli.download.failed", level="error", error=str(exc))
        exit_with_error(
            message=f"Invalid HuggingFace repo input: {exc}",
            detail="Use 'namespace/repo' or a full model URL on huggingface.co",
        )

    if args.cache_diagnostics:
        manager.print_cache_diagnostics()

    sys.exit(0)


__all__ = ["download_model_cli"]
