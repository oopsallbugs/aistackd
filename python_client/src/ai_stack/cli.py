#!/usr/bin/env python3
"""
Command-line interface for AI Stack
"""
import sys, time, subprocess, signal, os, shutil, argparse
from pathlib import Path

from .setup import SetupManager 
from .config import config
from .llm import create_client


def setup_cli():
    """CLI for setup command"""
    parser = argparse.ArgumentParser(description="AI Stack Setup")
    parser.parse_args()
    
    print("=" * 60)
    print("AI Stack Setup")
    print("=" * 60)
    
    manager = SetupManager()
    success = manager.setup()
    
    sys.exit(0 if success else 1)


def start_server_cli():
    """CLI for starting the server"""
    parser = argparse.ArgumentParser(description="Start AI Stack server")
    parser.add_argument("model", nargs="?", help="Model to use (filename or path)")
    parser.add_argument("--port", type=int, help="Port to run on")
    parser.add_argument("--host", help="Host to bind to")
    parser.add_argument("--detach", "-d", action="store_true", help="Run in background")
    parser.add_argument("--list", "-l", action="store_true", help="List available models and exit")
    
    args = parser.parse_args()
    
    # Handle --list flag
    if args.list:
        print("\nAvailable models:")
        models = config.get_available_models()
        if models:
            for i, model in enumerate(models, 1):
                print(f"  {i}. {model['name']} ({model['size_human']})")
            print("\nUsage:")
            if config.model.default_model:
                print(f"  server-start              # Use default: {Path(config.model.default_model).name}")
            print(f"  server-start <model_name>  # Start with a specific model")
            print(f"  server-start --list        # Show this list")
        else:
            print("  No models found in:", config.paths.models_dir)
            print("\nDownload a model first:")
            print("  download-model <url>")
        return
    
    # Update config if provided
    if args.port:
        config.server.port = args.port
    if args.host:
        config.server.host = args.host
    
    # Determine which model to use
    model_to_use = None
    
    if args.model:
        # User explicitly provided a model - use it
        model_to_use = args.model
        print(f"📝 Using explicitly specified model: {args.model}")
    elif config.model.default_model:
        # No model provided, but default exists - use default
        model_to_use = config.model.default_model
        default_name = Path(config.model.default_model).name
        print(f"📝 Using default model: {default_name}")
        print("   (Override by specifying a model: server-start <other-model>)")
    else:
        # No model provided and no default - error
        print("❌ Error: No model specified and no default model configured.")
        print("\nYou must specify which model to use:")
        
        # Show available models to help user
        models = config.get_available_models()
        if models:
            print("\nAvailable models:")
            for i, model in enumerate(models, 1):
                print(f"  {i}. {model['name']} ({model['size_human']})")
            print("\nOptions:")
            print("  1. Set a default model in config.py:")
            print("     USER_CONFIG['model']['default_model'] = 'path/to/model.gguf'")
            print("\n  2. Specify a model now:")
            for model in models[:3]:
                print(f"     server-start {model['name']}")
        else:
            print(f"\nNo models found in: {config.paths.models_dir}")
            print("Download a model first:")
            print("  download-model <url>")
        
        sys.exit(1)
    
    # Resolve model path
    resolved = config.resolve_model_path(model_to_use)
    if not resolved:
        # Model not found - show error (your existing error handling)
        print(f"❌ Error: Model not found: {model_to_use}")
        print("\n📋 Available models:")
        models = config.get_available_models()
        if models:
            for i, model in enumerate(models, 1):
                print(f"  {i}. {model['name']} ({model['size_human']})")
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
                
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

def _start_detached_server(manager, model_path: str):
    """Start server in background"""
    import subprocess
    import os
    
    # Create a detached process
    pid = os.fork()
    if pid == 0:
        # Child process
        os.setsid()
        # Redirect output to log file
        log_file = config.paths.script_dir / "server.log"
        with open(log_file, 'w') as f:
            f.write(f"Starting server at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Model: {model_path}\n")
            f.write(f"Endpoint: {config.server.llama_url}\n\n")
            f.flush()
            
            server = manager.start_server(model_path)
            # Keep running
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                server.terminate()
    else:
        # Parent process
        print(f"✅ Server started in background (PID: {pid})")
        print(f"   📍 Endpoint: {config.server.llama_url}")
        print(f"   📝 Log file: {config.paths.script_dir}/server.log")
        print("\n   Commands:")
        print("   server-status  - Check server status")
        print("   server-stop    - Stop the server")


def _start_foreground_server(manager, model_path: str):
    """Start server in foreground"""
    server = manager.start_server(model_path)
    
    print(f"\n✅ Server is running!")
    print(f"   📍 Endpoint: {config.server.llama_url}")
    print(f"   🔌 API: {config.server.llama_api_url}")
    print(f"\n   📦 Model: {Path(model_path).name}")
    print(f"   🎮 GPU Layers: {config.gpu.layers}")
    print(f"   📚 Context: {config.model.context_size}")
    print()
    print("   Press Ctrl+C to stop the server")
    print()
    
    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping server...")
        server.terminate()
        try:
            server.wait(timeout=5)
        except:
            server.kill()
        print("✅ Server stopped.")


def status_cli():
    """CLI for checking status"""
    print("=" * 60)
    print("AI Stack Status")
    print("=" * 60)
    
    # Show configuration summary
    config.print_summary()  # This now shows default model info
    
    # Check if server is running
    client = create_client()
    if client.health_check():
        print("\n✅ Server is running")
        
        # Get model info
        try:
            models = client.get_models()
            if models:
                print(f"   Loaded models: {', '.join(models)}")
            
            # Try to get more details
            model_info = client.get_model_info()
            if model_info:
                print(f"   Context size: {model_info.get('context_length', 'unknown')}")
        except Exception as e:
            print(f"   Could not get model info: {e}")
    else:
        print("\n❌ Server is not running")
        print("\nTo start the server:")
        models = config.get_available_models()
        if models:
            if config.model.default_model:
                default_name = Path(config.model.default_model).name
                print(f"  server-start              # Use default: {default_name}")
                print(f"  server-start <model_name> # Use a different model")
            else:
                print(f"  server-start {models[0]['name']}")
            print("  server-start --list        # See all models")
        else:
            print("  No models available. Download a model first:")
            print("  download-model <url>")

def stop_server_cli():
    """CLI for stopping the server"""
    print("🛑 Stopping AI Stack server...")
    
    # Find and kill llama-server process
    try:
        # Use pgrep to find llama-server processes
        result = subprocess.run(
            ["pgrep", "-f", "llama-server"],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid.strip():
                    print(f"  Stopping PID {pid}...")
                    os.kill(int(pid), signal.SIGTERM)
            
            # Give them a moment to terminate gracefully
            time.sleep(2)
            
            # Check if any are still running and force kill
            result2 = subprocess.run(
                ["pgrep", "-f", "llama-server"],
                capture_output=True,
                text=True
            )
            if result2.stdout.strip():
                remaining = result2.stdout.strip().split('\n')
                for pid in remaining:
                    if pid.strip():
                        print(f"  Force killing PID {pid}...")
                        os.kill(int(pid), signal.SIGKILL)
            
            print(f"✅ Stopped {len(pids)} server process(es)")
        else:
            print("ℹ️  No server processes found")
            
    except Exception as e:
        print(f"❌ Error stopping server: {e}")
        sys.exit(1)


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
        """
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
        manager.list_huggingface_files(args.repo)
        if args.cache_diagnostics:
            manager.print_cache_diagnostics()
        return
    
    success = manager.download_from_huggingface(
        repo_id=args.repo,
        filename=args.file,
        download_mmproj=args.mmproj,
        quant_preference=args.quant,
    )
    if args.cache_diagnostics:
        manager.print_cache_diagnostics()
    
    sys.exit(0 if success else 1)


def check_deps_cli():
    """CLI for checking dependencies"""
    manager = SetupManager()
    deps = manager.check_dependencies()
    
    print("=" * 60)
    print("Dependency Check")
    print("=" * 60)
    
    all_good = True
    for dep, installed in deps.items():
        status = "✅" if installed else "❌"
        print(f"{status} {dep}")
        if not installed:
            all_good = False
    
    if all_good:
        print("\n✅ All dependencies satisfied!")
    else:
        print("\n❌ Some dependencies are missing")
        print("\nRun 'setup-stack' to install missing dependencies")
    
    sys.exit(0 if all_good else 1)

def uninstall_cli():
    """CLI for uninstalling AI Stack"""
    
    print("=" * 60)
    print("🧹 AI Stack Uninstall")
    print("=" * 60)
    print("\nThis will remove:")
    print("  • llama.cpp build directory")
    print("  • All downloaded models")
    print("  • Configuration files")
    print("  • Manifest and cache")
    print()
    
    # Ask for confirmation
    response = input("Are you sure you want to uninstall? (y/N): ")
    if response.lower() != 'y':
        print("❌ Uninstall cancelled")
        return
    
    # Track what we remove
    removed = []
    failed = []
    
    # Remove models directory
    if config.paths.models_dir.exists():
        try:
            shutil.rmtree(config.paths.models_dir)
            removed.append(f"Models: {config.paths.models_dir}")
        except Exception as e:
            failed.append(f"Models: {e}")
    
    # Remove llama.cpp build
    if config.paths.llama_cpp_dir.exists():
        try:
            shutil.rmtree(config.paths.llama_cpp_dir)
            removed.append(f"llama.cpp: {config.paths.llama_cpp_dir}")
        except Exception as e:
            failed.append(f"llama.cpp: {e}")
    
    # Remove config cache if any
    config_cache = Path.home() / ".cache" / "ai_stack"
    if config_cache.exists():
        try:
            shutil.rmtree(config_cache)
            removed.append(f"Cache: {config_cache}")
        except Exception as e:
            failed.append(f"Cache: {e}")
    
    # Remove config file if in standard location
    config_file = Path.home() / ".config" / "ai_stack" / "config.json"
    if config_file.exists():
        try:
            config_file.unlink()
            removed.append(f"Config: {config_file}")
        except Exception as e:
            failed.append(f"Config: {e}")
    
    # Print results
    print("\n" + "=" * 60)
    if removed:
        print("✅ Removed:")
        for item in removed:
            print(f"  • {item}")
    
    if failed:
        print("\n❌ Failed to remove:")
        for item in failed:
            print(f"  • {item}")
    
    if not removed and not failed:
        print("✅ Nothing to remove - AI Stack not installed")
    
    print("\n📝 Note: To completely remove the package itself:")
    print("  pip uninstall ai-stack")


if __name__ == "__main__":
    print("🤖 AI Stack CLI - Available commands:")
    print("=" * 60)
    print("  setup-stack     - Run complete setup (build llama.cpp, install deps)")
    print("  server-start    - Start server (model name required unless default is set)")
    print("  server-status   - Check server status")
    print("  server-stop     - Stop server")
    print("  download-model  - Download a model")
    print("  check-deps      - Check dependencies")
    print("=" * 60)
    print("\nModel Selection:")
    print("  • If default model is set in config.py:")
    print("    server-start              # Uses default model")
    print("    server-start other.gguf   # Overrides default")
    print("  • If no default is set:")
    print("    server-start model.gguf   # Must specify model")
    print("\nExamples:")
    print("  server-start --list                    # List available models")
    print("  server-start llama-2-7b.Q4_K_M.gguf    # Start with specific model")
    print("  server-start --detach                   # Run in background")
    print("  download-model https://example.com/model.gguf")
