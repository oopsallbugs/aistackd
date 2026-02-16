"""
AI Stack Setup Manager - Handles installation and configuration
"""
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import config

class SetupManager:
    """Manages AI Stack setup without .env files"""
    
    def __init__(self):
        self.config = config
    
    def check_dependencies(self) -> Dict[str, bool]:
        """Check system dependencies"""
        deps = {
            "git": False,
            "cmake": False,
            "make": False,
            "python": True,  # We're running Python
            "pip": False,
        }
        
        # Check for pip
        try:
            subprocess.run([sys.executable, "-m", "pip", "--version"], 
                         capture_output=True, check=False)
            deps["pip"] = True
        except:
            pass
        
        # Check build tools
        for tool in ["git", "cmake", "make"]:
            try:
                subprocess.run([tool, "--version"], 
                             capture_output=True, check=False)
                deps[tool] = True
            except FileNotFoundError:
                pass
        
        # GPU-specific checks
        if self.config.gpu.vendor == "nvidia":
            try:
                subprocess.run(["nvidia-smi"], 
                             capture_output=True, check=False)
                deps["nvidia_driver"] = True
            except:
                deps["nvidia_driver"] = False
        
        elif self.config.gpu.vendor == "amd":
            try:
                subprocess.run(["hipconfig", "--version"], 
                             capture_output=True, check=False)
                deps["rocm"] = True
            except:
                deps["rocm"] = False
        
        return deps
    
    def clone_llama_cpp(self, force: bool = False) -> bool:
        """Clone llama.cpp repository"""
        if self.config.paths.llama_cpp_dir.exists():
            if force:
                import shutil
                shutil.rmtree(self.config.paths.llama_cpp_dir)
            else:
                print(f"✓ llama.cpp already exists at {self.config.paths.llama_cpp_dir}")
                return True
        
        print(f"Cloning llama.cpp to {self.config.paths.llama_cpp_dir}...")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", 
                 "https://github.com/ggerganov/llama.cpp.git", 
                 str(self.config.paths.llama_cpp_dir)],
                capture_output=True,
                text=True,
                check=True
            )
            print("✓ Cloned llama.cpp")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to clone: {e}")
            if e.stderr:
                print(f"  Error: {e.stderr.strip()}")
            return False
    
    def build_llama_cpp(self) -> bool:
        """Build llama.cpp with auto-detected GPU support"""
        if self.config.is_llama_built:
            print("✓ llama.cpp already built")
            return True
        
        print(f"Building llama.cpp for {self.config.gpu.vendor.upper()}...")
        
        # Set up build environment
        env = os.environ.copy()
        build_env = []
        
        # Set HIP environment for AMD
        if self.config.gpu.vendor == "amd":
            try:
                result = subprocess.run(
                    ["hipconfig", "-R"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                env["HIP_PATH"] = result.stdout.strip()
                
                result = subprocess.run(
                    ["hipconfig", "-l"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                env["HIPCXX"] = result.stdout.strip()
                
                # Set HSA override if needed
                if self.config.gpu.hsa_override_gfx_version:
                    env["HSA_OVERRIDE_GFX_VERSION"] = self.config.gpu.hsa_override_gfx_version
                
                build_env.append(f"HIP_PATH={env['HIP_PATH']}")
                build_env.append(f"HIPCXX={env['HIPCXX']}")
                
            except Exception as e:
                print(f"⚠ Warning: Could not set HIP environment: {e}")
        
        # Build commands
        build_dir = self.config.paths.llama_cpp_dir / "build"
        build_dir.mkdir(exist_ok=True)
        
        try:
            # Configure
            cmake_cmd = ["cmake", "..", "-DCMAKE_BUILD_TYPE=Release"]
            cmake_cmd.extend(self.config.gpu.cmake_flags)
            
            print(f"  Configuring with: {' '.join(cmake_cmd)}")
            
            result = subprocess.run(
                cmake_cmd,
                cwd=build_dir,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Build
            import multiprocessing
            cores = multiprocessing.cpu_count()
            
            print(f"  Building with {cores} cores...")
            
            result = subprocess.run(
                ["cmake", "--build", ".", "--config", "Release", "-j", str(cores)],
                cwd=build_dir,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Verify build
            if self.config.llama_server_binary.exists():
                print("✓ Built llama.cpp successfully")
                return True
            else:
                print("✗ Build completed but llama-server not found")
                return False
                
        except subprocess.CalledProcessError as e:
            print(f"✗ Build failed:")
            if e.stdout:
                print(f"  Output: {e.stdout.strip()[:500]}...")
            if e.stderr:
                print(f"  Error: {e.stderr.strip()[:500]}...")
            return False
    
    def download_model(self, model_url: str, filename: Optional[str] = None) -> bool:
        """Download a model file"""
        import urllib.request
        
        if not self.config.paths.models_dir.exists():
            self.config.paths.models_dir.mkdir(parents=True)
        
        if not filename:
            filename = model_url.split("/")[-1]
        
        output_path = self.config.paths.models_dir / filename
        
        if output_path.exists():
            print(f"✓ Model already exists: {filename}")
            return True
        
        print(f"Downloading model: {filename}")
        
        try:
            # Simple download with progress
            def report_progress(block_num, block_size, total_size):
                downloaded = block_num * block_size
                if total_size > 0:
                    percent = min(100, downloaded * 100 / total_size)
                    print(f"\r  Progress: {percent:.1f}%", end="", flush=True)
            
            urllib.request.urlretrieve(
                model_url,
                output_path,
                report_progress
            )
            print(f"\n✓ Downloaded: {filename}")
            return True
            
        except Exception as e:
            print(f"\n✗ Download failed: {e}")
            return False
    
    def start_server(self, 
                    model_path: Optional[str] = None,
                    mmproj_path: Optional[str] = None) -> subprocess.Popen:
        """Start llama.cpp server"""
        
        if not self.config.is_llama_built:
            raise RuntimeError("llama.cpp is not built. Run setup() first.")
        
        # Use first available model if none specified
        if not model_path:
            models = self.config.get_available_models()
            if not models:
                raise RuntimeError("No models available. Download models first.")
            model_path = models[0]["path"]
        
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        # Build command
        cmd = [
            str(self.config.llama_server_binary),
            "-m", str(model_path),
            "--host", self.config.server.host,
            "--port", str(self.config.server.port),
            "-c", str(self.config.model.context_size),
            "-ngl", str(self.config.gpu.layers)
        ]
        
        if mmproj_path and Path(mmproj_path).exists():
            cmd.extend(["--mmproj", mmproj_path])
        
        print(f"Starting server: {' '.join(cmd)}")
        
        # Set environment for GPU
        env = os.environ.copy()
        if (self.config.gpu.vendor == "amd" and 
            self.config.gpu.hsa_override_gfx_version):
            env["HSA_OVERRIDE_GFX_VERSION"] = self.config.gpu.hsa_override_gfx_version
        
        # Start server
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for server to start
        print("Waiting for server to start...", end="", flush=True)
        for _ in range(30):  # 30 second timeout
            try:
                import requests
                response = requests.get(
                    f"{self.config.server.llama_url}/health",
                    timeout=1
                )
                if response.status_code == 200:
                    print(" ✓")
                    print(f"Server started on {self.config.server.llama_url}")
                    return process
            except:
                pass
            print(".", end="", flush=True)
            time.sleep(1)
        
        print(" ✗")
        process.terminate()
        raise RuntimeError("Server failed to start within 30 seconds")
    
    def setup(self) -> bool:
        """Complete setup process"""
        print("=" * 60)
        print("AI Stack Setup")
        print("=" * 60)
        
        # Show current configuration
        self.config.print_summary()
        
        # Check dependencies
        print("\n1. Checking dependencies...")
        deps = self.check_dependencies()
        
        missing_critical = [d for d, s in deps.items() 
                          if not s and d in ["git", "cmake", "make"]]
        
        if missing_critical:
            print("✗ Missing critical dependencies:")
            for dep in missing_critical:
                print(f"  • {dep}")
            print("\nPlease install missing dependencies and try again.")
            return False
        
        print("✓ All dependencies satisfied")
        
        # Clone llama.cpp
        print("\n2. Setting up llama.cpp...")
        if not self.clone_llama_cpp():
            return False
        
        # Build llama.cpp
        print("\n3. Building llama.cpp...")
        if not self.build_llama_cpp():
            return False
        
        print("\n" + "=" * 60)
        print("Setup complete!")
        print("=" * 60)
        
        # Show next steps
        print("\nNext steps:")
        if not self.config.has_models:
            print("1. Download models:")
            print(f"   mkdir -p {self.config.paths.models_dir}")
            print("   # Download GGUF models from HuggingFace")
        else:
            print("1. Start server:")
            print(f"   from ai_stack.setup import SetupManager")
            print(f"   manager = SetupManager()")
            print(f"   server = manager.start_server()")
        
        print(f"\n2. Use the LLM client:")
        print(f"   from ai_stack.llm import create_client")
        print(f"   client = create_client()")
        print(f"   response = client.chat([{{'role': 'user', 'content': 'Hello'}}])")
        
        return True