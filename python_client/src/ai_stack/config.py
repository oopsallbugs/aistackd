"""
AI Stack Configuration - Auto-detects GPU, models, and paths for llama.cpp and RAG server. 
Provides a unified configuration object for the entire AI stack.
"""
import os, sys, subprocess, platform, re, json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from functools import cached_property

# =============================================================================
# USER CONFIGURATION – SINGLE SOURCE OF TRUTH
# Change any value here to override the default.
# =============================================================================
USER_CONFIG = {
    "gpu": {
        "vendor": "auto",          # "auto", "nvidia", "amd", "metal", "cpu"
        "target": "",              # e.g., "gfx1100" ("" means auto-detect)
        "hsa_override_gfx_version": "",
        "layers": 99,
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
        "rag_host": "127.0.0.1",
        "rag_port": 8081,
    },
    "model": {                     # Model params for llama.cpp server
        "default_model": None,     # Must be set manually or provided at runtime (e.g, start-server "Qwen3-4B.Q4_K_M.gguf")
        "temperature": 1.0,
        "top_p": 0.95,
        "min_p": 0.01,
        "max_tokens": 2000,
        "repeat_penalty": 1.0,
        "context_size": 32768,
    },
    "paths": {
        "script_dir": None,        # None = auto-detect from file location
        "llama_cpp_dir": None,
        "models_dir": None,
        "ai_stack_dir": None,
    },
    "manifest": {
        "auto_update": True,           # Auto-update manifest on model / mmproj downloads
        "path": "models/manifest.json", # Optional custom manifest location
        "backup_on_change": True       # Backup manifest before updating
    }
}
# =============================================================================

@dataclass
class GPUConfig:
    vendor: str
    target: str
    hsa_override_gfx_version: str
    layers: int

    def auto_detect(self):
        """Fill in missing values (vendor="auto" or target="") by detecting hardware."""
        system = platform.system()
        
        if system == "Linux":
            self._detect_linux_gpu()
        elif system == "Darwin":
            self.vendor = "metal"
            self.layers = 99
        elif system == "Windows":
            self._detect_windows_gpu()
    
    def _detect_linux_gpu(self):
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
                
                # If no target found so far, prompt user (only if vendor is auto or target is empty)
                if not self.target:
                    print("\nCould not auto-detect AMD GPU architecture.")
                    print("Please select your GPU series:")
                    print("  1. RDNA3 (RX 7000 series) - gfx1100")
                    print("  2. RDNA2 (RX 6000 series) - gfx1030")
                    print("  3. CDNA (Instinct/MI series) - gfx908")
                    print("  4. Vega (RX 5000/Vega) - gfx900")
                    choice = input("Enter choice (1-4) [1]: ") or "1"

                    # Map choice to target
                    target_map = {
                        "1": "gfx1100",
                        "2": "gfx1030", 
                        "3": "gfx908",
                        "4": "gfx900"
                    }
                    self.target = target_map.get(choice, "gfx1100")
                    print(f"  Selected target: {self.target}")
                  
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
        self.vendor = "cpu"
        self.layers = 0
        print("  Windows GPU detection not implemented, using CPU")
    
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
class ServerConfig:
    host: str
    port: int
    rag_host: str
    rag_port: int

    @cached_property
    def llama_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @cached_property
    def rag_url(self) -> str:
        return f"http://{self.rag_host}:{self.rag_port}"

@dataclass
class ModelConfig:
    default_model: Optional[str]
    temperature: float
    top_p: float
    min_p: float
    max_tokens: int
    repeat_penalty: float
    context_size: int

@dataclass
class PathConfig:
    script_dir: Path
    llama_cpp_dir: Path
    models_dir: Path
    ai_stack_dir: Path

class AiStackConfig:
    def __init__(self, user_config: Dict[str, Any] = None):
        if user_config is None:
            user_config = USER_CONFIG

        # Create each dataclass by unpacking the corresponding sub‑dictionary
        self.gpu = GPUConfig(**user_config["gpu"])
        self.server = ServerConfig(**user_config["server"])
        self.model = ModelConfig(**user_config["model"])
        self.paths = PathConfig(**{
            k: Path(v) if v is not None else None
            for k, v in user_config["paths"].items()
        })
        
        # Model Manifest configuration
        self.manifest_path = Path(user_config["manifest"]["path"])
        self.manifest_auto_update = user_config["manifest"]["auto_update"]
        self.manifest_backup_on_change = user_config["manifest"]["backup_on_change"]
        self.manifest = self._load_manifest()  # Load manifest data (e.g., available models) at startup
        
        # Initialize available models list
        self._available_models = self.manifest.get("models", []) if self.manifest else []

        # Now run auto‑detection for fields that need it
        self._auto_detect_all()

    def _load_manifest(self) -> dict:
        """Load or create manifest"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        # Create default manifest
        return {
            "models": [],
            "mmproj_files": []
        }
    
    def _save_manifest(self):
        """Save manifest to disk"""
        # Create models directory if it doesn't exist
        self.paths.models_dir.mkdir(parents=True, exist_ok=True)
        
        # Add backup if enabled
        if self.manifest_backup_on_change and self.manifest_path.exists():
            backup_path = self.manifest_path.with_suffix('.json.bak')
            import shutil
            shutil.copy2(self.manifest_path, backup_path)
        
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)
    
    def backup_manifest(self):  # Add this method
        """Backup manifest file"""
        if self.manifest_path.exists():
            backup_path = self.manifest_path.with_suffix('.json.bak')
            import shutil
            shutil.copy2(self.manifest_path, backup_path)
            print(f"📋 Manifest backed up to {backup_path}")
    
    def add_model_to_manifest(self, 
                            model_path: Path, 
                            source_url: Optional[str] = None,
                            mmproj_path: Optional[Path] = None,
                            family: Optional[str] = None,
                            metadata: Optional[Dict] = None):
        """Add a model to the manifest"""
        model_name = model_path.name
        
        # Check if model already exists
        for model in self.manifest["models"]:
            if model["name"] == model_name:
                # Update existing entry
                model["path"] = str(model_path)
                if source_url:
                    model["source_url"] = source_url
                if mmproj_path:
                    model["mmproj"] = str(mmproj_path)
                    model["requires_mmproj"] = True
                if metadata:
                    model["metadata"] = metadata
                model["downloaded_at"] = datetime.now().isoformat()
                self._save_manifest()
                return
        
        # Add new model
        model_entry = {
            "name": model_name,
            "path": str(model_path),
            "requires_mmproj": mmproj_path is not None,
            "downloaded_at": datetime.now().isoformat()
        }
        
        if source_url:
            # Extract repo_id from URL
            if 'huggingface.co' in source_url:
                model_entry["repo"] = source_url.split('huggingface.co/')[-1]
            model_entry["source_url"] = source_url
        
        if mmproj_path:
            model_entry["mmproj"] = str(mmproj_path)
        
        if family:
            model_entry["family"] = family
        
        if metadata:
            model_entry["metadata"] = metadata
        
        self.manifest["models"].append(model_entry)
        self._save_manifest()
    
    def add_mmproj_to_manifest(self, 
                            mmproj_path: Path,
                            for_models: List[str],
                            source_url: Optional[str] = None):
        """Add an MMproj file to the manifest"""
        mmproj_name = mmproj_path.name
        
        # Check if MMproj already exists
        for mmproj in self.manifest["mmproj_files"]:
            if mmproj["name"] == mmproj_name:
                # Update existing
                mmproj["path"] = str(mmproj_path)
                mmproj["for_models"] = list(set(mmproj["for_models"] + for_models))
                if source_url:
                    mmproj["source_url"] = source_url
                mmproj["downloaded_at"] = datetime.now().isoformat()
                self._save_manifest()
                return
        
        # Add new MMproj
        mmproj_entry = {
            "name": mmproj_name,
            "path": str(mmproj_path),
            "for_models": for_models,
            "downloaded_at": datetime.now().isoformat()
        }
        
        if source_url:
            mmproj_entry["source_url"] = source_url
        
        self.manifest["mmproj_files"].append(mmproj_entry)
        self._save_manifest()
    
    def get_mmproj_for_model(self, model_path: Path) -> Optional[Path]:
        """Get MMproj path from manifest first, then fallback to other methods"""
        model_name = model_path.name
        
        # First, check in models list for direct mmproj reference
        for model in self.manifest["models"]:
            if model["name"] == model_name:
                if model.get("requires_mmproj") and model.get("mmproj"):
                    mmproj_path = Path(model["mmproj"])
                    if mmproj_path.exists():
                        return mmproj_path
        
        # Second, check mmproj_files for any that list this model
        for mmproj in self.manifest["mmproj_files"]:
            if model_name in mmproj.get("for_models", []):
                mmproj_path = Path(mmproj["path"])
                if mmproj_path.exists():
                    return mmproj_path
        
        # Fallback to convention-based detection
        return self.find_mmproj_for_model(model_path)

    def _auto_detect_all(self):
        """Apply auto‑detection logic where values are "auto", None, or ""."""
        # GPU detection if vendor is "auto" or target missing
        if self.gpu.vendor == "auto" or not self.gpu.target:
            self.gpu.auto_detect()

        # Path auto‑detection
        if self.paths.script_dir is None:
            self.paths.script_dir = Path(__file__).parent.parent.parent.parent.resolve()
        if self.paths.llama_cpp_dir is None:
            self.paths.llama_cpp_dir = self.paths.script_dir / "llama.cpp"
        if self.paths.models_dir is None:
            self.paths.models_dir = self.paths.script_dir / "models"
        if self.paths.ai_stack_dir is None:
            self.paths.ai_stack_dir = self.paths.script_dir / "python_client" / "src" / "ai_stack"

        # Auto-detect available models (for discovery only)
        self._auto_detect_models()
        
        # Validate that the configured model exists (if set)
        self._validate_model_exists()

    def _auto_detect_models(self):
        """Auto-detect available GGUF models (for discovery only, not auto-selection)"""
        self._available_models = []
        if self.paths.models_dir.exists():
            for gguf in self.paths.models_dir.glob("*.gguf"):
                if "mmproj" not in gguf.name.lower():
                    self._available_models.append(gguf)
    
    def _validate_model_exists(self):
        """Check if the specified model exists (if one is configured)"""
        if self.model.default_model is None:
            # No model configured - that's fine, we'll just warn but not error
            # The CLI will handle requiring a model at runtime
            return
        
        model_path = Path(self.model.default_model)
        if not model_path.exists():
            # Try relative to models_dir
            alt_path = self.paths.models_dir / model_path
            if alt_path.exists():
                # Update to the full path
                self.model.default_model = str(alt_path)
                return
            
            # Model not found - show helpful error
            if self._available_models:
                model_list = "\n  • ".join([str(m.name) for m in self._available_models[:5]])
                msg = (
                    f"Configured model not found: {model_path}\n"
                    f"Available models in {self.paths.models_dir}:\n  • {model_list}"
                )
                if len(self._available_models) > 5:
                    msg += f"\n  ... and {len(self._available_models) - 5} more"
            else:
                msg = (
                    f"Configured model not found: {model_path}\n"
                    f"No models found in {self.paths.models_dir}. "
                    "Please download a .gguf model first."
                )
            raise FileNotFoundError(msg)
        
    def resolve_model_path(self, model_arg: str) -> Optional[Path]:
        """Resolve a model argument to a full path"""
        model_path = Path(model_arg)
        
        # Check if it's a full path
        if model_path.exists():
            return model_path
        
        # Check if it's just a filename in the models directory
        alt_path = self.paths.models_dir / model_path
        if alt_path.exists():
            return alt_path
        
        # Try adding .gguf extension if not present
        if not model_arg.endswith('.gguf'):
            alt_path = self.paths.models_dir / f"{model_arg}.gguf"
            if alt_path.exists():
                return alt_path
        
        # Try case-insensitive match
        if self.paths.models_dir.exists():
            for f in self.paths.models_dir.glob("*.gguf"):
                if f.name.lower() == model_arg.lower() or f.name.lower() == f"{model_arg.lower()}.gguf":
                    return f
        
        return None
    
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
        return len(self._available_models) > 0
    
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
        
        # Default model if set
        if self.model.default_model:
            print(f"\nDefault Model: {Path(self.model.default_model).name}")
        else:
            print(f"\nDefault Model: Not set (must specify at runtime)")
        
        print("\n" + "=" * 60)


# Global instance
config = AiStackConfig()