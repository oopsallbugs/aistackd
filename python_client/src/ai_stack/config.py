"""
AI Stack Configuration - Auto-detects GPU, models, and paths for llama.cpp and RAG server. 
Provides a unified configuration object for the entire AI stack.
"""
import os
import sys
import subprocess
import platform
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from functools import cached_property

# Centralized config for the AI stack
@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 8080
    rag_host: str = "127.0.0.1"  # RAG should be local-only
    rag_port: int = 8081
    
    @cached_property
    def llama_url(self) -> str:
        return f"http://{self.host}:{self.port}"
    
    @cached_property
    def llama_api_url(self) -> str:
        return f"{self.llama_url}/v1"
    
    @cached_property
    def rag_url(self) -> str:
        return f"http://{self.rag_host}:{self.rag_port}"

@dataclass
class ModelConfig:
    """Model configuration"""
    default_model: Optional[str] = None
    temperature: float = 1.0
    top_p: float = 0.95
    min_p: float = 0.01
    max_tokens: int = 2000
    repeat_penalty: float = 1.0
    context_size: int = 32768

@dataclass
class GPUConfig:
    """GPU configuration with auto-detection"""
    vendor: str = "cpu"
    target: str = ""
    hsa_override_gfx_version: str = ""
    layers: int = 99
    
    def __post_init__(self):
        """Auto-detect GPU if not provided"""
        if self.vendor == "cpu" and self.target == "":
            self._auto_detect_gpu()
    
    def _auto_detect_gpu(self):
        """Auto-detect GPU configuration"""
        system = platform.system()
        
        if system == "Linux":
            self._detect_linux_gpu()
        elif system == "Darwin":
            self.vendor = "metal"
            self.layers = 99  # Metal uses all layers
        elif system == "Windows":
            self._detect_windows_gpu()
    
@dataclass
class GPUConfig:
    """GPU configuration with auto-detection"""
    vendor: str = "cpu"
    target: str = ""
    hsa_override_gfx_version: str = ""
    layers: int = 99
    
    def __post_init__(self):
        """Auto-detect GPU if not provided"""
        if self.vendor == "cpu" and self.target == "":
            self._auto_detect_gpu()
    
    def _auto_detect_gpu(self):
        """Auto-detect GPU configuration"""
        system = platform.system()
        
        if system == "Linux":
            self._detect_linux_gpu()
        elif system == "Darwin":
            self.vendor = "metal"
            self.layers = 99  # Metal uses all layers
        elif system == "Windows":
            self._detect_windows_gpu()
    
    def _detect_linux_gpu(self):  # ← This needs to be indented inside the class
        """Detect GPU on Linux"""
        try:
            # Check for NVIDIA first
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0 and result.stdout.strip():
                    self.vendor = "nvidia"
                    self.layers = 99
                    print(f"  Detected NVIDIA GPU: {result.stdout.strip()}")
                    return
            except:
                pass
            
            # Check for AMD (ROCm)
            if os.path.exists("/dev/kfd"):
                self.vendor = "amd"
                self.layers = 99
                
                # Try rocminfo
                try:
                    result = subprocess.run(
                        ["rocminfo"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        output = result.stdout
                        
                        # Look for gfx architecture
                        match = re.search(r'Name:\s+(gfx[0-9]{4})', output)
                        if match:
                            self.target = match.group(1)
                            print(f"  Detected AMD GPU via rocminfo: {self.target}")
                        else:
                            match = re.search(r'amdgcn-amd-amdhsa--(gfx[0-9]{4})', output)
                            if match:
                                self.target = match.group(1)
                                print(f"  Detected AMD GPU via ISA: {self.target}")
                            else:
                                for line in output.split('\n'):
                                    if 'gfx' in line.lower():
                                        gfx_match = re.search(r'(gfx[0-9]{4})', line)
                                        if gfx_match:
                                            self.target = gfx_match.group(1)
                                            print(f"  Detected AMD GPU via line match: {self.target}")
                                            break
                except Exception as e:
                    print(f"  rocminfo detection failed: {e}")
                
                # If no target found, default to gfx1100
                if not self.target:
                    self.target = "gfx1100"
                    print(f"  Using default target: {self.target}")
                
                # Set HSA override
                if self.target.startswith('gfx11'):
                    self.hsa_override_gfx_version = "11.0.0"
                elif self.target.startswith('gfx10'):
                    self.hsa_override_gfx_version = "10.3.0"
                elif self.target.startswith('gfx9'):
                    self.hsa_override_gfx_version = "9.0.6"
                else:
                    self.hsa_override_gfx_version = "11.0.0"
                
                print(f"  HSA override: {self.hsa_override_gfx_version}")
                return
                
        except Exception as e:
            print(f"  GPU detection error: {e}")
        
        # Fallback check for AMD
        if os.path.exists("/dev/kfd"):
            print("  /dev/kfd exists but detection failed, defaulting to AMD")
            self.vendor = "amd"
            self.target = "gfx1100"
            self.hsa_override_gfx_version = "11.0.0"
            self.layers = 99
            return
        
        # Default to CPU
        self.vendor = "cpu"
        self.layers = 0
        print("  No GPU detected, using CPU")
    
    def _detect_windows_gpu(self):
        """Detect GPU on Windows (placeholder)"""
        pass
    
    @property
    def cmake_flags(self) -> list:
        """Get CMake flags for this GPU configuration"""
        if self.vendor == "nvidia":
            return ["-DGGML_CUDA=ON"]
        elif self.vendor == "amd":
            flags = ["-DGGML_HIP=ON"]
            if self.target:
                flags.append(f"-DGPU_TARGETS={self.target}")
            return flags
        elif self.vendor == "metal":
            return ["-DGGML_METAL=ON"]
        else:
            return []  # CPU-only
    
    def _detect_windows_gpu(self):
        """Detect GPU on Windows (placeholder)"""
        # Windows typically uses DirectML or CUDA
        # Could implement WMI queries here
        pass
    
    @property
    def cmake_flags(self) -> list:
        """Get CMake flags for this GPU configuration"""
        if self.vendor == "nvidia":
            return ["-DGGML_CUDA=ON"]
        elif self.vendor == "amd":
            flags = ["-DGGML_HIP=ON"]
            if self.target:
                flags.append(f"-DGPU_TARGETS={self.target}")
            return flags
        elif self.vendor == "metal":
            return ["-DGGML_METAL=ON"]
        else:
            return []  # CPU-only
        
@dataclass
class PathConfig:
    """Path configuration with auto-detection"""
    script_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.resolve())
    llama_cpp_dir: Path = field(init=False)
    models_dir: Path = field(init=False)
    ai_stack_dir: Path = field(init=False)
    
    def __post_init__(self):
        """Set up paths relative to script directory"""
        self.script_dir = self.script_dir.resolve()
        self.llama_cpp_dir = self.script_dir / "llama.cpp"
        self.models_dir = self.script_dir / "models"
        self.ai_stack_dir = self.script_dir / "python_client" / "src" / "ai_stack"

class GenerateLocalConfig:
    """Main AI configuration with auto-detection"""
    
    def __init__(self):
        self.gpu = GPUConfig()
        self.paths = PathConfig()
        self.server = ServerConfig()
        self.model = ModelConfig()
        
        # Auto-detect available models
        self._auto_detect_models()
    
    def _auto_detect_models(self):
        """Auto-detect available GGUF models"""
        if self.paths.models_dir.exists():
            gguf_files = list(self.paths.models_dir.glob("*.gguf"))
            if gguf_files:
                # Sort by size (largest first)
                gguf_files.sort(key=lambda x: x.stat().st_size, reverse=True)
                self.model.default_model = str(gguf_files[0])
    
    @cached_property
    def llama_server_binary(self) -> Path:
        """Get path to llama-server binary"""
        return self.paths.llama_cpp_dir / "build" / "bin" / "llama-server"
    
    @cached_property
    def is_llama_built(self) -> bool:
        """Check if llama.cpp is built"""
        return self.llama_server_binary.exists()
    
    @cached_property
    def has_models(self) -> bool:
        """Check if any models are available"""
        return self.paths.models_dir.exists() and any(
            self.paths.models_dir.glob("*.gguf")
        )
    
    def get_available_models(self) -> list:
        """Get list of available GGUF models"""
        if not self.paths.models_dir.exists():
            return []
        
        models = []
        for gguf in self.paths.models_dir.glob("*.gguf"):
            # Skip mmproj files (vision model projectors)
            if "mmproj" not in gguf.name.lower():
                size_mb = gguf.stat().st_size / (1024 * 1024)
                models.append({
                    "path": str(gguf),
                    "name": gguf.name,
                    "size_mb": round(size_mb, 1),
                    "size_human": self._format_size(gguf.stat().st_size)
                })
        
        return sorted(models, key=lambda x: x["size_mb"], reverse=True)
    
    @staticmethod
    def _format_size(bytes: int) -> str:
        """Format bytes to human readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes < 1024.0:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.1f} PB"
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary"""
        return {
            "gpu": {
                "vendor": self.gpu.vendor,
                "target": self.gpu.target,
                "hsa_override_gfx_version": self.gpu.hsa_override_gfx_version,
                "layers": self.gpu.layers
            },
            "paths": {
                "script_dir": str(self.paths.script_dir),
                "llama_cpp_dir": str(self.paths.llama_cpp_dir),
                "models_dir": str(self.paths.models_dir),
                "ai_stack_dir": str(self.paths.ai_stack_dir)
            },
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "rag_host": self.server.rag_host,
                "rag_port": self.server.rag_port,
                "llama_url": self.server.llama_url,
                "rag_url": self.server.rag_url
            },
            "model": {
                "default_model": self.model.default_model,
                "temperature": self.model.temperature,
                "top_p": self.model.top_p,
                "min_p": self.model.min_p,
                "max_tokens": self.model.max_tokens,
                "repeat_penalty": self.model.repeat_penalty,
                "context_size": self.model.context_size
            },
            "status": {
                "llama_built": self.is_llama_built,
                "has_models": self.has_models
            }
        }
    
    def print_summary(self):
        """Print configuration summary"""
        print("=" * 60)
        print("AI Stack Configuration")
        print("=" * 60)
        
        # GPU Info
        print(f"\nGPU Configuration:")
        print(f"  Vendor: {self.gpu.vendor.upper()}")
        if self.gpu.target:
            print(f"  Target: {self.gpu.target}")
        if self.gpu.hsa_override_gfx_version:
            print(f"  HSA Version: {self.gpu.hsa_override_gfx_version}")
        print(f"  Layers: {self.gpu.layers}")
        
        # Server Info
        print(f"\nServer Configuration:")
        print(f"  Llama: {self.server.llama_url}")
        print(f"  RAG: {self.server.rag_url}")
        
        # Paths
        print(f"\nPaths:")
        print(f"  Script Directory: {self.paths.script_dir}")
        print(f"  Models Directory: {self.paths.models_dir}")
        
        # Status
        print(f"\nStatus:")
        print(f"  Llama built: {'✓' if self.is_llama_built else '✗'}")
        print(f"  Models available: {'✓' if self.has_models else '✗'}")
        
        # Available models
        models = self.get_available_models()
        if models:
            print(f"\nAvailable Models:")
            for model in models[:5]:  # Show top 5
                print(f"  • {model['name']} ({model['size_human']})")
            if len(models) > 5:
                print(f"  ... and {len(models) - 5} more")
        
        print("\n" + "=" * 60)

# Global configuration instance
config = GenerateLocalConfig()