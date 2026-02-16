#!/usr/bin/env python3
"""
Command-line interface for AI Stack
"""
import sys
import argparse
import time
from pathlib import Path

from .setup import SetupManager 
from .config import config
from .llm import create_client


def setup_cli():
    """CLI for setup command"""
    parser = argparse.ArgumentParser(description="AI Stack Setup")
    # The setup() method doesn't take arguments, so keep it simple
    parser.parse_args()
    
    print("=" * 60)
    print("AI Stack Setup")
    print("=" * 60)
    
    manager = SetupManager()
    # setup() takes no arguments based on your dir output
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
        else:
            print("  No models found in:", config.paths.models_dir)
        return
    
    # Update config if provided
    if args.port:
        config.server.port = args.port
    if args.host:
        config.server.host = args.host
    
    # Handle model selection
    model_path = None
    if args.model:
        # Check if it's a full path
        if Path(args.model).exists():
            model_path = args.model
        else:
            # Check if it's just a filename in the models directory
            full_path = config.paths.models_dir / args.model
            if full_path.exists():
                model_path = str(full_path)
            else:
                # Try adding .gguf extension if not present
                if not args.model.endswith('.gguf'):
                    full_path = config.paths.models_dir / f"{args.model}.gguf"
                    if full_path.exists():
                        model_path = str(full_path)
                
        if not model_path:
            print(f"Error: Model not found: {args.model}")
            print("\nAvailable models:")
            models = config.get_available_models()
            if models:
                for i, model in enumerate(models, 1):
                    print(f"  {i}. {model['name']} ({model['size_human']})")
                print("\nTry one of these names:")
                for model in models[:3]:  # Show first 3 as examples
                    print(f"  start {model['name']}")
            else:
                print("  No models found in:", config.paths.models_dir)
            sys.exit(1)
    else:
        # No model specified, try to use default or pick one
        models = config.get_available_models()
        if not models:
            print("Error: No models available. Please download a model first.")
            print(f"Models directory: {config.paths.models_dir}")
            sys.exit(1)
        
        # Use the first model as default
        model_path = models[0]['path']
        print(f"No model specified, using: {models[0]['name']}")
    
    manager = SetupManager()
    
    try:
        print(f"Starting server on {config.server.llama_url}...")
        print(f"Model: {model_path}")
        
        if args.detach:
            # Run in background
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
                print(f"   Endpoint: {config.server.llama_url}")
                print(f"   Log file: {config.paths.script_dir}/server.log")
                print("   Use 'server-stop' to stop it")
                print("   Use 'server-status' to check status")
        else:
            # Run in foreground
            server = manager.start_server(model_path)
            print(f"\n✅ Server is running!")
            print(f"   Endpoint: {config.server.llama_url}")
            print(f"   API: {config.server.llama_api_url}")
            print(f"\n   Model: {Path(model_path).name}")
            print(f"   GPU Layers: {config.gpu.layers}")
            print(f"   Context: {config.model.context_size}")
            print()
            print("   Press Ctrl+C to stop the server")
            print()
            
            try:
                # Keep the script running
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n\nStopping server...")
                server.terminate()
                try:
                    server.wait(timeout=5)
                except:
                    server.kill()
                print("✅ Server stopped.")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def status_cli():
    """CLI for checking status"""
    print("=" * 60)
    print("AI Stack Status")
    print("=" * 60)
    
    # Show configuration
    config.print_summary()
    
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
            print(f"  server-start {models[0]['name']}  # Start with first model")
            print("  server-start --list              # See all models")
        else:
            print("  No models available. Download a model first.")

def stop_server_cli():
    """CLI for stopping the server"""
    import subprocess
    import signal
    import os
    
    print("Stopping AI Stack server...")
    
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
            print("No server processes found")
            
    except Exception as e:
        print(f"Error stopping server: {e}")
        sys.exit(1)


def download_model_cli():
    """CLI for downloading models"""
    parser = argparse.ArgumentParser(description="Download a model")
    parser.add_argument("url", help="URL of the model to download")
    parser.add_argument("--filename", help="Filename to save as")
    
    args = parser.parse_args()
    
    manager = SetupManager()
    success = manager.download_model(args.url, args.filename)
    
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
    
    sys.exit(0 if all_good else 1)


if __name__ == "__main__":
    # If run directly, show available commands
    print("AI Stack CLI - Available commands:")
    print("  setup-stack    - Run complete setup")
    print("  server-start   - Start server")
    print("  server-status  - Check status")
    print("  server-stop    - Stop server")
    print("  download-model - Download a model")
    print("  check-deps     - Check dependencies")