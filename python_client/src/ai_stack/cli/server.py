"""Server-related CLI commands."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests

from ai_stack.core.config import config
from ai_stack.core.exceptions import AiStackError
from ai_stack.llm import create_client
from ai_stack.stack.manager import SetupManager

from ai_stack.cli.main import extract_context_size


def _runtime_dir() -> Path:
    return config.paths.script_dir / ".ai_stack"


def _server_pid_path() -> Path:
    return _runtime_dir() / "server.pid"


def _load_server_pid() -> Optional[dict]:
    pid_path = _server_pid_path()
    if not pid_path.exists():
        return None
    try:
        return json.loads(pid_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_server_pid(pid: int, model_path: str) -> None:
    runtime_dir = _runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _server_pid_path().write_text(
        json.dumps(
            {
                "pid": pid,
                "model_path": model_path,
                "endpoint": config.server.llama_url,
                "started_at": int(time.time()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _clear_server_pid() -> None:
    pid_path = _server_pid_path()
    if pid_path.exists():
        pid_path.unlink()


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _terminate_process(pid: int, timeout_seconds: float = 8.0) -> bool:
    if not _is_process_running(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _is_process_running(pid):
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    time.sleep(0.2)
    return not _is_process_running(pid)


def start_server_cli():
    """CLI for starting the server"""
    parser = argparse.ArgumentParser(description="Start AI Stack server")
    parser.add_argument("model", nargs="?", help="Model to use (filename or path)")
    parser.add_argument("--port", type=int, help="Port to run on")
    parser.add_argument("--host", help="Host to bind to")
    parser.add_argument("--detach", "-d", action="store_true", help="Run in background")
    parser.add_argument("--list", "-l", action="store_true", help="List available models and exit")

    args = parser.parse_args()

    if args.list:
        print("\nAvailable models:")
        models = config.get_available_models()
        if models:
            for idx, model in enumerate(models, 1):
                print(f"  {idx}. {model['name']} ({model['size_human']})")
            print("\nUsage:")
            if config.model.default_model:
                print(f"  server-start              # Use default: {Path(config.model.default_model).name}")
            print("  server-start <model_name>  # Start with a specific model")
            print("  server-start --list        # Show this list")
        else:
            print("  No models found in:", config.paths.models_dir)
            print("\nDownload a model first:")
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
        print("❌ Error: No model specified and no default model configured.")
        print("\nYou must specify which model to use:")
        models = config.get_available_models()
        if models:
            print("\nAvailable models:")
            for idx, model in enumerate(models, 1):
                print(f"  {idx}. {model['name']} ({model['size_human']})")
            print("\nOptions:")
            print("  1. Set a default model in config.py:")
            print("     USER_CONFIG['model']['default_model'] = 'path/to/model.gguf'")
            print("\n  2. Specify a model now:")
            for model in models[:3]:
                print(f"     server-start {model['name']}")
        else:
            print(f"\nNo models found in: {config.paths.models_dir}")
            print("Download a model first:")
            print("  download-model <namespace/repo or hf-url>")
        sys.exit(1)

    resolved = config.resolve_model_path(model_to_use)
    if not resolved:
        print(f"❌ Error: Model not found: {model_to_use}")
        print("\n📋 Available models:")
        models = config.get_available_models()
        if models:
            for idx, model in enumerate(models, 1):
                print(f"  {idx}. {model['name']} ({model['size_human']})")
        sys.exit(1)
    model_path = str(resolved)

    manager = SetupManager()

    try:
        print(f"\n🚀 Starting server on {config.server.llama_url}...")
        print(f"📦 Model: {Path(model_path).name}")
        if args.port or args.host:
            print(f"🌐 Custom endpoint: {config.server.llama_url}")

        if args.detach:
            _start_detached_server(manager, model_path)
        else:
            _start_foreground_server(manager, model_path)

    except (AiStackError, OSError) as exc:
        print(f"❌ Error: {exc}")
        sys.exit(1)


def _start_detached_server(manager, model_path: str):
    """Start server in background"""
    existing = _load_server_pid()
    if existing:
        try:
            existing_pid = int(existing.get("pid", 0))
        except (TypeError, ValueError):
            existing_pid = 0
        if _is_process_running(existing_pid):
            print("ℹ️  A managed detached server is already running.")
            print(f"   PID: {existing_pid}")
            print(f"   📍 Endpoint: {config.server.llama_url}")
            print("   Use `server-stop` first if you want to restart it.")
            return
        _clear_server_pid()

    log_file = config.paths.script_dir / "server.log"
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

    _write_server_pid(server.pid, model_path)
    print(f"✅ Server started in background (PID: {server.pid})")
    print(f"   📍 Endpoint: {config.server.llama_url}")
    print(f"   📝 Log file: {log_file}")
    print("\n   Commands:")
    print("   server-status  - Check server status")
    print("   server-stop    - Stop the server")


def _start_foreground_server(manager, model_path: str):
    """Start server in foreground"""
    server = manager.start_server(model_path)

    print("\n✅ Server is running!")
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


def status_cli():
    """CLI for checking status"""
    print("=" * 60)
    print("AI Stack Status")
    print("=" * 60)

    config.print_summary(show_header=False)

    client = create_client()
    if client.health_check():
        print("\n✅ Server is running")
        try:
            models = client.get_models()
            if models:
                print(f"   Loaded models: {', '.join(models)}")

            model_info = client.get_model_info()
            if model_info:
                context_size = extract_context_size(model_info)
                if context_size is not None:
                    print(f"   Context size: {context_size}")
                else:
                    print("   Context size: unknown (/props did not include a recognized context field)")
        except (requests.RequestException, ValueError, TypeError, KeyError, OSError) as exc:
            print(f"   Could not get model info: {exc}")
    else:
        print("\n❌ Server is not running")
        print("\nTo start the server:")
        models = config.get_available_models()
        if models:
            if config.model.default_model:
                default_name = Path(config.model.default_model).name
                print(f"  server-start              # Use default: {default_name}")
                print("  server-start <model_name> # Use a different model")
            else:
                print(f"  server-start {models[0]['name']}")
            print("  server-start --list        # See all models")
        else:
            print("  No models available. Download a model first:")
            print("  download-model <namespace/repo or hf-url>")


def stop_server_cli(argv=None):
    """CLI for stopping the server"""
    parser = argparse.ArgumentParser(description="Stop detached AI Stack server")
    parser.parse_args(argv)

    print("🛑 Stopping AI Stack server...")

    pid_record = _load_server_pid()
    if not pid_record:
        print("ℹ️  No managed detached server found (missing PID file).")
        return

    try:
        pid = int(pid_record.get("pid", 0))
    except (TypeError, ValueError):
        pid = 0

    if not _is_process_running(pid):
        print("ℹ️  PID file exists but process is not running. Cleaning up stale state.")
        _clear_server_pid()
        return

    print(f"  Stopping PID {pid}...")
    if _terminate_process(pid):
        _clear_server_pid()
        print("✅ Server stopped")
        return

    print(f"❌ Failed to stop PID {pid}")
    sys.exit(1)


__all__ = [
    "start_server_cli",
    "status_cli",
    "stop_server_cli",
    "_start_detached_server",
    "_start_foreground_server",
    "_runtime_dir",
    "_server_pid_path",
    "_load_server_pid",
    "_write_server_pid",
    "_clear_server_pid",
    "_is_process_running",
    "_terminate_process",
]
