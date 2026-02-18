"""
AI Stack Configuration - Auto-detects GPU, models, and paths for llama.cpp and RAG server.
Provides a unified configuration object for the entire AI stack.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_stack.llama import detect_gpu

# =============================================================================
# USER CONFIGURATION - SINGLE SOURCE OF TRUTH
# Change any value here to override the default.
# =============================================================================
USER_CONFIG = {
    "gpu": {
        "vendor": "auto",  # "auto", "nvidia", "amd", "metal", "cpu"
        "target": "",  # e.g., "gfx1100" ("" means auto-detect)
        "hsa_override_gfx_version": "",
        "layers": 99,
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
        "rag_host": "127.0.0.1",
        "rag_port": 8081,
    },
    "model": {
        "default_model": None,
        "temperature": 1.0,
        "top_p": 0.95,
        "min_p": 0.01,
        "max_tokens": 2000,
        "repeat_penalty": 1.0,
        "context_size": 32768,
    },
    "paths": {
        "project_root": None,
        "llama_cpp_dir": None,
        "models_dir": None,
    },
}
# =============================================================================


@dataclass
class GPUConfig:
    vendor: str
    target: str
    hsa_override_gfx_version: str
    layers: int

    def auto_detect(self, verbose: bool = False, fallback_amd_target: str = "gfx1100") -> None:
        """Fill in missing values (vendor='auto' or target='') by detecting hardware."""
        detect_gpu.auto_detect_gpu(
            config=self,
            verbose=verbose,
            fallback_amd_target=fallback_amd_target,
        )

    # Backward-compatible wrappers used by tests and legacy callers.
    def _detect_linux_gpu(self, verbose: bool = False, fallback_amd_target: str = "gfx1100") -> None:
        detect_gpu.detect_linux_gpu(
            config=self,
            verbose=verbose,
            fallback_amd_target=fallback_amd_target,
        )

    def _detect_windows_gpu(self, verbose: bool = False) -> None:
        detect_gpu.detect_windows_gpu(config=self, verbose=verbose)

    @property
    def cmake_flags(self) -> list:
        """Get CMake flags for this GPU configuration"""
        if self.vendor == "nvidia":
            return ["-DGGML_CUDA=ON"]
        if self.vendor == "amd":
            flags = ["-DGGML_HIP=ON"]
            if self.target:
                flags.append(f"-DGPU_TARGETS={self.target}")
            return flags
        if self.vendor == "metal":
            return ["-DGGML_METAL=ON"]
        return []


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
    def llama_api_url(self) -> str:
        return f"{self.llama_url}/v1"

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
    project_root: Path
    llama_cpp_dir: Path
    models_dir: Path


class AiStackConfig:
    def __init__(self, user_config: Dict[str, Any] = None):
        if user_config is None:
            user_config = USER_CONFIG

        self.gpu = GPUConfig(**user_config["gpu"])
        self.server = ServerConfig(**user_config["server"])
        self.model = ModelConfig(**user_config["model"])
        self.paths = PathConfig(
            **{k: Path(v) if v is not None else None for k, v in user_config["paths"].items()}
        )

        self._available_models: List[Path] = []
        self._auto_detect_all()

    def _auto_detect_all(self):
        """Apply auto-detection logic where values are 'auto', None, or ''"""
        if self.gpu.vendor == "auto" or not self.gpu.target:
            verbose_detect = os.environ.get("AI_STACK_VERBOSE_DETECT", "").strip() == "1"
            fallback_amd_target = os.environ.get("AI_STACK_AMD_TARGET", "").strip() or "gfx1100"
            self.gpu.auto_detect(
                verbose=verbose_detect,
                fallback_amd_target=fallback_amd_target,
            )

        if self.paths.project_root is None:
            self.paths.project_root = Path(__file__).resolve().parents[4]
        if self.paths.llama_cpp_dir is None:
            self.paths.llama_cpp_dir = self.paths.project_root / "llama.cpp"
        if self.paths.models_dir is None:
            self.paths.models_dir = self.paths.project_root / "models"

        self._auto_detect_models()
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
            return

        model_path = Path(self.model.default_model)
        if model_path.exists():
            return

        alt_path = self.paths.models_dir / model_path
        if alt_path.exists():
            self.model.default_model = str(alt_path)
            return

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

        if model_path.exists():
            return model_path

        alt_path = self.paths.models_dir / model_path
        if alt_path.exists():
            return alt_path

        if not model_arg.endswith(".gguf"):
            alt_path = self.paths.models_dir / f"{model_arg}.gguf"
            if alt_path.exists():
                return alt_path

        if self.paths.models_dir.exists():
            for gguf in self.paths.models_dir.glob("*.gguf"):
                if gguf.name.lower() == model_arg.lower() or gguf.name.lower() == f"{model_arg.lower()}.gguf":
                    return gguf

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
            if "mmproj" not in gguf.name.lower():
                size_mb = gguf.stat().st_size / (1024 * 1024)
                models.append(
                    {
                        "path": str(gguf),
                        "name": gguf.name,
                        "size_mb": round(size_mb, 1),
                        "size_human": self._format_size(gguf.stat().st_size),
                    }
                )

        return sorted(models, key=lambda item: item["size_mb"], reverse=True)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes to human readable size"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def to_dict(self) -> dict:
        """Convert configuration to dictionary"""
        return {
            "gpu": {
                "vendor": self.gpu.vendor,
                "target": self.gpu.target,
                "hsa_override_gfx_version": self.gpu.hsa_override_gfx_version,
                "layers": self.gpu.layers,
            },
            "paths": {
                "project_root": str(self.paths.project_root),
                "llama_cpp_dir": str(self.paths.llama_cpp_dir),
                "models_dir": str(self.paths.models_dir),
            },
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "rag_host": self.server.rag_host,
                "rag_port": self.server.rag_port,
                "llama_url": self.server.llama_url,
                "rag_url": self.server.rag_url,
            },
            "model": {
                "default_model": self.model.default_model,
                "temperature": self.model.temperature,
                "top_p": self.model.top_p,
                "min_p": self.model.min_p,
                "max_tokens": self.model.max_tokens,
                "repeat_penalty": self.model.repeat_penalty,
                "context_size": self.model.context_size,
            },
            "status": {
                "llama_built": self.is_llama_built,
                "has_models": self.has_models,
            },
        }

    def print_summary(self, show_header: bool = True):
        """Print configuration summary"""
        if show_header:
            print("=" * 60)
            print("AI Stack Configuration")
            print("=" * 60)

        print("\nGPU Configuration:")
        print(f"  Vendor: {self.gpu.vendor.upper()}")
        if self.gpu.target:
            print(f"  Target: {self.gpu.target}")
        if self.gpu.hsa_override_gfx_version:
            print(f"  HSA Version: {self.gpu.hsa_override_gfx_version}")
        print(f"  Layers: {self.gpu.layers}")

        print("\nServer Configuration:")
        print(f"  Llama: {self.server.llama_url}")
        print(f"  RAG: {self.server.rag_url}")

        print("\nPaths:")
        print(f"  Project Root: {self.paths.project_root}")
        print(f"  Models Directory: {self.paths.models_dir}")

        print("\nStatus:")
        print(f"  Llama built: {'✓' if self.is_llama_built else '✗'}")
        print(f"  Models available: {'✓' if self.has_models else '✗'}")

        models = self.get_available_models()
        if models:
            print("\nAvailable Models:")
            for model in models[:5]:
                print(f"  • {model['name']} ({model['size_human']})")
            if len(models) > 5:
                print(f"  ... and {len(models) - 5} more")

        if self.model.default_model:
            print(f"\nDefault Model: {Path(self.model.default_model).name}")
        else:
            print("\nDefault Model: Not set (must specify at runtime)")

        if show_header:
            print("\n" + "=" * 60)


config = AiStackConfig()

__all__ = [
    "AiStackConfig",
    "GPUConfig",
    "ModelConfig",
    "PathConfig",
    "ServerConfig",
    "USER_CONFIG",
    "config",
]
