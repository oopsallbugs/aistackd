"""AI Stack setup and orchestration manager."""

from __future__ import annotations

import subprocess
import sys
from typing import Dict, Optional

from ai_stack.core.config import config
from ai_stack.huggingface.cache import HuggingFaceSnapshotCache
from ai_stack.huggingface.client import HuggingFaceClient
from ai_stack.llama.build import build_llama_cpp, clone_llama_cpp
from ai_stack.llama.server import start_llama_server
from ai_stack.models.registry import ModelRegistry
from . import hf_downloads


class SetupManager:
    """Manages AI Stack setup and runtime orchestration."""

    def __init__(self):
        self.config = config
        self.registry = ModelRegistry(models_dir=self.config.paths.models_dir)
        self.registry.ensure_manifest()
        self.hf = HuggingFaceClient()
        runtime_dir = self.config.paths.project_root / ".ai_stack"
        self.hf_cache = HuggingFaceSnapshotCache(cache_path=runtime_dir / "huggingface" / "cache.json")
        self.hf_cache_diagnostics = {
            "miss": 0,
            "hit": 0,
            "refresh": 0,
            "fallback": 0,
        }

    def _record_cache_event(self, event: str) -> None:
        if event in self.hf_cache_diagnostics:
            self.hf_cache_diagnostics[event] += 1

    def get_cache_diagnostics(self) -> Dict[str, int]:
        return dict(self.hf_cache_diagnostics)

    def print_cache_diagnostics(self) -> None:
        stats = self.get_cache_diagnostics()
        print("\n📊 HF cache diagnostics")
        print(f"   miss: {stats['miss']}")
        print(f"   hit: {stats['hit']}")
        print(f"   refresh: {stats['refresh']}")
        print(f"   fallback: {stats['fallback']}")

    @staticmethod
    def normalize_hf_repo_id(repo_input: str) -> str:
        return hf_downloads.normalize_hf_repo_id(repo_input)

    def check_dependencies(self) -> Dict[str, bool]:
        """Check system dependencies."""
        deps = {
            "git": False,
            "cmake": False,
            "make": False,
            "python": True,
            "pip": False,
        }

        try:
            subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, check=False)
            deps["pip"] = True
        except OSError:
            pass

        for tool in ["git", "cmake", "make"]:
            try:
                subprocess.run([tool, "--version"], capture_output=True, check=False)
                deps[tool] = True
            except FileNotFoundError:
                pass

        if self.config.gpu.vendor == "nvidia":
            try:
                subprocess.run(["nvidia-smi"], capture_output=True, check=False)
                deps["nvidia_driver"] = True
            except OSError:
                deps["nvidia_driver"] = False
        elif self.config.gpu.vendor == "amd":
            try:
                subprocess.run(["hipconfig", "--version"], capture_output=True, check=False)
                deps["rocm"] = True
            except OSError:
                deps["rocm"] = False

        return deps

    def clone_llama_cpp(self, force: bool = False) -> bool:
        """Clone llama.cpp repository."""
        return clone_llama_cpp(config=self.config, force=force)

    def build_llama_cpp(self) -> bool:
        """Build llama.cpp with auto-detected GPU support."""
        return build_llama_cpp(config=self.config)

    def _get_hf_snapshot(self, repo_id: str, revision: str = "main"):
        return hf_downloads.get_hf_snapshot(
            hf_client=self.hf,
            hf_cache=self.hf_cache,
            record_cache_event=self._record_cache_event,
            repo_id=repo_id,
            revision=revision,
        )

    def list_huggingface_files(self, repo_id: str):
        """List available files in a HuggingFace repo (GGUF + mmproj)."""
        repo_id = self.normalize_hf_repo_id(repo_id)
        snap = self._get_hf_snapshot(repo_id=repo_id, revision="main")
        hf_downloads.list_huggingface_files(snapshot=snap)

    def download_from_huggingface(
        self,
        repo_id: str,
        filename: Optional[str] = None,
        download_mmproj: bool = False,
        quant_preference: Optional[str] = None,
    ) -> bool:
        repo_id = self.normalize_hf_repo_id(repo_id)
        print(f"🔍 Fetching info for {repo_id}...")
        snap = self._get_hf_snapshot(repo_id=repo_id, revision="main")
        return hf_downloads.download_from_huggingface(
            config=self.config,
            registry=self.registry,
            hf_client=self.hf,
            snapshot=snap,
            repo_id=repo_id,
            filename=filename,
            download_mmproj=download_mmproj,
            quant_preference=quant_preference,
        )

    def start_server(
        self,
        model_path: Optional[str] = None,
        mmproj_path: Optional[str] = None,
        stdout=None,
        stderr=None,
    ):
        """Start llama.cpp server."""
        return start_llama_server(
            config=self.config,
            registry=self.registry,
            model_path=model_path,
            mmproj_path=mmproj_path,
            stdout=stdout,
            stderr=stderr,
        )

    def setup(self) -> bool:
        """Complete setup process."""
        print("=" * 60)
        print("AI Stack Setup")
        print("=" * 60)

        self.config.print_summary()

        print("\n1. Checking dependencies...")
        deps = self.check_dependencies()

        missing_critical = [dep for dep, installed in deps.items() if not installed and dep in ["git", "cmake", "make"]]
        if missing_critical:
            print("✗ Missing critical dependencies:")
            for dep in missing_critical:
                print(f"  • {dep}")
            print("\nPlease install missing dependencies and try again.")
            return False

        print("✓ All dependencies satisfied")

        print("\n2. Setting up llama.cpp...")
        if not self.clone_llama_cpp():
            return False

        print("\n3. Building llama.cpp...")
        if not self.build_llama_cpp():
            return False

        print("\n" + "=" * 60)
        print("Setup complete!")
        print("=" * 60)

        print("\nNext steps:")
        if not self.config.has_models:
            print("1. Download models:")
            print(f"   mkdir -p {self.config.paths.models_dir}")
            print("   # Download GGUF models from HuggingFace")
            print("   # Example: download-model TheBloke/Llama-2-7B-GGUF")
        else:
            print("1. Start server with a specific model:")
            print("   from ai_stack.stack.manager import SetupManager")
            print("   manager = SetupManager()")
            print("   server = manager.start_server('models/your-model.gguf')")
            print("   # Or via CLI: server-start your-model.gguf")

        print("\n2. Use the LLM client:")
        print("   from ai_stack.llm import create_client")
        print("   client = create_client()")
        print("   response = client.chat([{'role': 'user', 'content': 'Hello'}])")

        return True


__all__ = ["SetupManager"]
