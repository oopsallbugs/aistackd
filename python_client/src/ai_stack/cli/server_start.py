"""Start command logic for server CLI."""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path


def start_server_cli(
    *,
    config,
    setup_manager_cls,
    exit_with_error,
    ai_stack_error_cls,
    start_detached_fn,
    start_foreground_fn,
    print_section,
    print_bullet_list,
):
    """CLI for starting the server."""
    parser = argparse.ArgumentParser(description="Start AI Stack server")
    parser.add_argument("model", nargs="?", help="Model to use (filename or path)")
    parser.add_argument("--port", type=int, help="Port to run on")
    parser.add_argument("--host", help="Host to bind to")
    parser.add_argument("--detach", "-d", action="store_true", help="Run in background")
    parser.add_argument("--list", "-l", action="store_true", help="List available models and exit")

    args = parser.parse_args()

    if args.list:
        print_section("Available models:")
        models = config.get_available_models()
        if models:
            rows = [f"{idx}. {model['name']} ({model['size_human']})" for idx, model in enumerate(models, 1)]
            print_bullet_list(rows, prefix="  ")
            print_section("Usage:")
            if config.model.default_model:
                print(f"  server-start              # Use default: {Path(config.model.default_model).name}")
            print("  server-start <model_name>  # Start with a specific model")
            print("  server-start --list        # Show this list")
        else:
            print("  No models found in:", config.paths.models_dir)
            print_section("Download a model first:")
            print("  download-model <namespace/repo or hf-url>")
        return

    if args.port:
        config.server.port = args.port
    if args.host:
        config.server.host = args.host

    model_to_use = None
    if args.model:
        model_to_use = args.model
        print(f"📝 Using explicitly specified model: {args.model}")
    elif config.model.default_model:
        model_to_use = config.model.default_model
        default_name = Path(config.model.default_model).name
        print(f"📝 Using default model: {default_name}")
        print("   (Override by specifying a model: server-start <other-model>)")
    else:
        details = ["You must specify which model to use:"]
        models = config.get_available_models()
        if models:
            details.extend(["", "Available models:"])
            for idx, model in enumerate(models, 1):
                details.append(f"  {idx}. {model['name']} ({model['size_human']})")
            details.extend(
                [
                    "",
                    "Options:",
                    "  1. Set a default model in config.py:",
                    "     USER_CONFIG['model']['default_model'] = 'path/to/model.gguf'",
                    "",
                    "  2. Specify a model now:",
                ]
            )
            for model in models[:3]:
                details.append(f"     server-start {model['name']}")
        else:
            details.extend(
                [
                    "",
                    f"No models found in: {config.paths.models_dir}",
                    "Download a model first:",
                    "  download-model <namespace/repo or hf-url>",
                ]
            )
        exit_with_error(
            message="No model specified and no default model configured.",
            detail="\n".join(details),
        )

    resolved = config.resolve_model_path(model_to_use)
    if not resolved:
        details = [f"📋 Available models:"]
        models = config.get_available_models()
        if models:
            for idx, model in enumerate(models, 1):
                details.append(f"  {idx}. {model['name']} ({model['size_human']})")
        exit_with_error(message=f"Model not found: {model_to_use}", detail="\n".join(details))
    model_path = str(resolved)

    manager = setup_manager_cls()

    try:
        print_section(f"🚀 Starting server on {config.server.llama_url}...")
        print(f"📦 Model: {Path(model_path).name}")
        if args.port or args.host:
            print(f"🌐 Custom endpoint: {config.server.llama_url}")

        if args.detach:
            start_detached_fn(manager, model_path)
        else:
            start_foreground_fn(manager, model_path)

    except (ai_stack_error_cls, OSError) as exc:
        exit_with_error(message=str(exc))


def start_detached_server(
    *,
    config,
    load_server_pid_fn,
    is_process_running_fn,
    clear_server_pid_fn,
    write_server_pid_fn,
    manager,
    model_path: str,
    print_section,
):
    """Start server in background."""
    existing = load_server_pid_fn()
    if existing:
        try:
            existing_pid = int(existing.get("pid", 0))
        except (TypeError, ValueError):
            existing_pid = 0
        if is_process_running_fn(existing_pid):
            print("ℹ️  A managed detached server is already running.")
            print(f"   PID: {existing_pid}")
            print(f"   📍 Endpoint: {config.server.llama_url}")
            print("   Use `server-stop` first if you want to restart it.")
            return
        clear_server_pid_fn()

    log_file = config.paths.project_root / "server.log"
    with open(log_file, "a", encoding="utf-8") as log_handle:
        log_handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting detached server\n")
        log_handle.write(f"Model: {model_path}\n")
        log_handle.write(f"Endpoint: {config.server.llama_url}\n\n")
        log_handle.flush()
        server = manager.start_server(
            model_path,
            stdout=log_handle,
            stderr=log_handle,
        )

    write_server_pid_fn(server.pid, model_path)
    print(f"✅ Server started in background (PID: {server.pid})")
    print(f"   📍 Endpoint: {config.server.llama_url}")
    print(f"   📝 Log file: {log_file}")
    print_section("   Commands:")
    print("   server-status  - Check server status")
    print("   server-stop    - Stop the server")


def start_foreground_server(*, config, manager, model_path: str, print_section):
    """Start server in foreground."""
    server = manager.start_server(model_path)

    print_section("✅ Server is running!")
    print(f"   📍 Endpoint: {config.server.llama_url}")
    print(f"   🔌 API: {config.server.llama_api_url}")
    print(f"\n   📦 Model: {Path(model_path).name}")
    print(f"   🎮 GPU Layers: {config.gpu.layers}")
    print(f"   📚 Context: {config.model.context_size}")
    print()
    print("   Press Ctrl+C to stop the server")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping server...")
        server.terminate()
        try:
            server.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            server.kill()
        print("✅ Server stopped.")


__all__ = ["start_detached_server", "start_foreground_server", "start_server_cli"]
