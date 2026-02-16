"""
Python client for llama.cpp setup
"""
import os
import json
import subprocess
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
from .config import config

class LlamaClient:
    """Client for managing llama.cpp setup"""
    
    def __init__(self):
        self.config = config
        self.server_process = None
    
    def check_dependencies(self) -> Dict[str, bool]:
        """Check system dependencies"""
        deps = {
            "git": False,
            "cmake": False,
            "make": False,
            "python": False,
            "pip": False,
        }
        
        for dep in deps.keys():
            try:
                subprocess.run([dep, "--version"], capture_output=True, check=False)
                deps[dep] = True
            except FileNotFoundError:
                pass
        
        # GPU-specific checks
        if self.config.gpu.vendor == "nvidia":
            try:
                subprocess.run(["nvidia-smi"], capture_output=True, check=False)
                deps["nvidia_driver"] = True
            except:
                deps["nvidia_driver"] = False
        
        elif self.config.gpu.vendor == "amd":
            try:
                subprocess.run(["hipconfig", "--version"], capture_output=True, check=False)
                deps["rocm"] = True
            except:
                deps["rocm"] = False
        
        return deps
    
    def clone_llama_cpp(self, force: bool = False) -> bool:
        """Clone or update llama.cpp repository"""
        target_dir = self.config.paths.llama_cpp_dir
        
        if os.path.exists(target_dir):
            if force:
                import shutil
                shutil.rmtree(target_dir)
            else:
                print(f"✓ llama.cpp already exists at {target_dir}")
                print("  Updating repository...")
                try:
                    subprocess.run(
                        ["git", "pull"],
                        cwd=target_dir,
                        check=True,
                        capture_output=True
                    )
                    return True
                except subprocess.CalledProcessError:
                    print("  Warning: Failed to update, using existing")
                    return True
        
        print(f"Cloning llama.cpp to {target_dir}...")
        try:
            subprocess.run(
                ["git", "clone", "https://github.com/ggerganov/llama.cpp.git", target_dir],
                check=True,
                capture_output=True
            )
            print("✓ Cloned llama.cpp")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to clone: {e}")
            return False
    
    def build_llama_cpp(self) -> bool:
        """Build llama.cpp with appropriate GPU support"""
        build_dir = os.path.join(self.config.paths.llama_cpp_dir, "build")
        
        if os.path.exists(os.path.join(build_dir, "bin", "llama-server")):
            print("✓ llama.cpp already built")
            return True
        
        print("Building llama.cpp...")
        
        # Set up build environment
        env = os.environ.copy()
        
        # Configure CMake flags based on GPU vendor
        cmake_flags = ["-DCMAKE_BUILD_TYPE=Release"]
        
        if self.config.gpu.vendor == "nvidia":
            cmake_flags.append("-DGGML_CUDA=ON")
            print("  Building with CUDA support...")
        
        elif self.config.gpu.vendor == "amd":
            cmake_flags.append("-DGGML_HIP=ON")
            if self.config.gpu.target:
                cmake_flags.append(f"-DGPU_TARGETS={self.config.gpu.target}")
            print(f"  Building with HIP/ROCm support ({self.config.gpu.target})...")
            
            # Set HIP environment variables
            try:
                hip_path = subprocess.run(
                    ["hipconfig", "-R"],
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout.strip()
                env["HIP_PATH"] = hip_path
                
                hipcxx = subprocess.run(
                    ["hipconfig", "-l"],
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout.strip()
                env["HIPCXX"] = hipcxx
            except:
                print("  Warning: Could not set HIP environment variables")
        
        else:
            print("  Building CPU-only version...")
        
        try:
            # Configure
            subprocess.run(
                ["cmake", "-S", ".", "-B", "build"] + cmake_flags,
                cwd=self.config.paths.llama_cpp_dir,
                env=env,
                check=True,
                capture_output=True
            )
            
            # Build
            import multiprocessing
            cores = multiprocessing.cpu_count()
            
            subprocess.run(
                ["cmake", "--build", "build", "--config", "Release", "--", f"-j{cores}"],
                cwd=self.config.paths.llama_cpp_dir,
                env=env,
                check=True,
                capture_output=True
            )
            
            print("✓ Built llama.cpp successfully")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"✗ Build failed: {e}")
            return False
    
    def start_server(self, model_path: str, mmproj_path: Optional[str] = None) -> bool:
        """Start llama.cpp server with given model"""
        server_binary = os.path.join(
            self.config.paths.llama_cpp_dir,
            "build",
            "bin",
            "llama-server"
        )
        
        if not os.path.exists(server_binary):
            print(f"✗ Server binary not found: {server_binary}")
            return False
        
        # Build command
        cmd = [
            server_binary,
            "-m", model_path,
            "--host", self.config.server.host,
            "--port", str(self.config.server.port),
            "-c", "4096",  # Context size
            "-ngl", str(self.config.gpu.layers)
        ]
        
        if mmproj_path and os.path.exists(mmproj_path):
            cmd.extend(["--mmproj", mmproj_path])
        
        # Set environment variables for GPU
        env = os.environ.copy()
        if self.config.gpu.vendor == "amd" and self.config.gpu.hsa_override_gfx_version:
            env["HSA_OVERRIDE_GFX_VERSION"] = self.config.gpu.hsa_override_gfx_version
        
        print(f"Starting server: {' '.join(cmd)}")
        
        try:
            self.server_process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait a moment for server to start
            time.sleep(3)
            
            # Check if server is responsive
            if self.check_server_health():
                print(f"✓ Server started on {self.config.llama_url}")
                return True
            else:
                print("✗ Server started but not responding")
                return False
                
        except Exception as e:
            print(f"✗ Failed to start server: {e}")
            return False
    
    def check_server_health(self) -> bool:
        """Check if server is healthy"""
        import requests
        
        try:
            response = requests.get(f"{self.config.llama_url}/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def stop_server(self):
        """Stop llama.cpp server"""
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
                print("✓ Server stopped")
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                print("✗ Server forcefully killed")
            self.server_process = None
    
    def list_models(self) -> List[str]:
        """List available models in models directory"""
        models_dir = self.config.paths.models_dir
        
        if not os.path.exists(models_dir):
            return []
        
        models = []
        for file in os.listdir(models_dir):
            if file.endswith(".gguf"):
                models.append(file)
        
        return sorted(models)

# Example usage
if __name__ == "__main__":
    client = LlamaClient()
    
    print(client.config)
    
    # Check dependencies
    deps = client.check_dependencies()
    print("\nDependencies:")
    for dep, status in deps.items():
        print(f"  {dep}: {'✓' if status else '✗'}")
    
    # Example: Clone and build
    # client.clone_llama_cpp()
    # client.build_llama_cpp()
    
    # Example: Start server with a model
    # models = client.list_models()
    # if models:
    #     model_path = os.path.join(client.config.paths.models_dir, models[0])
    #     client.start_server(model_path)
    
    # Keep server running
    # try:
    #     while True:
    #         time.sleep(1)
    # except KeyboardInterrupt:
    #     client.stop_server()