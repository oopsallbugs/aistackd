"""Model download CLI commands."""

from __future__ import annotations

import argparse
import sys

from huggingface_hub.errors import HFValidationError

from ai_stack.core.errors import exit_with_error
from ai_stack.stack.manager import SetupManager


def download_model_cli():
    """CLI for downloading models from HuggingFace"""
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
            manager.list_huggingface_files(args.repo)
        except (HFValidationError, ValueError) as exc:
            exit_with_error(
                message=f"Invalid HuggingFace repo input: {exc}",
                detail="Use 'namespace/repo' or a full model URL on huggingface.co",
            )
        if args.cache_diagnostics:
            manager.print_cache_diagnostics()
        return

    try:
        success = manager.download_from_huggingface(
            repo_id=args.repo,
            filename=args.file,
            download_mmproj=args.mmproj,
            quant_preference=args.quant,
        )
    except (HFValidationError, ValueError) as exc:
        exit_with_error(
            message=f"Invalid HuggingFace repo input: {exc}",
            detail="Use 'namespace/repo' or a full model URL on huggingface.co",
        )

    if args.cache_diagnostics:
        manager.print_cache_diagnostics()

    sys.exit(0 if success else 1)


__all__ = ["download_model_cli"]
