"""AI Stack setup and orchestration manager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from ai_stack.core.config import config
from ai_stack.huggingface.cache import HuggingFaceSnapshotCache
from ai_stack.huggingface.client import HuggingFaceClient
from ai_stack.huggingface.metadata import derive_model_metadata
from ai_stack.huggingface.resolver import DEFAULT_QUANT_RANKING, resolve_download
from ai_stack.llama.build import build_llama_cpp, clone_llama_cpp
from ai_stack.llama.server import start_llama_server
from ai_stack.models.registry import ModelRegistry


class SetupManager:
    """Manages AI Stack setup and runtime orchestration."""

    def __init__(self):
        self.config = config
        self.registry = ModelRegistry(models_dir=self.config.paths.models_dir)
        self.registry.ensure_manifest()
        self.hf = HuggingFaceClient()
        runtime_dir = self.config.paths.script_dir / ".ai_stack"
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
        """
        Accept either:
        - namespace/repo
        - https://huggingface.co/namespace/repo[/...]
        and normalize to namespace/repo.
        """
        value = (repo_input or "").strip()
        if not value:
            raise ValueError("Repo cannot be empty. Use format: namespace/repo")

        if "://" not in value:
            return value

        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        if host not in {"huggingface.co", "www.huggingface.co"}:
            raise ValueError(f"Unsupported host '{parsed.netloc}'. Expected huggingface.co")

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Could not parse repo from URL. Expected: https://huggingface.co/namespace/repo")

        if parts[0] in {"models", "spaces", "datasets"}:
            if parts[0] != "models":
                raise ValueError("Only model repos are supported. Use a model URL or namespace/repo.")
            if len(parts) < 3:
                raise ValueError(
                    "Could not parse model repo from URL. Expected: https://huggingface.co/models/namespace/repo"
                )
            return f"{parts[1]}/{parts[2]}"

        return f"{parts[0]}/{parts[1]}"

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
        except Exception:
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
            except Exception:
                deps["nvidia_driver"] = False
        elif self.config.gpu.vendor == "amd":
            try:
                subprocess.run(["hipconfig", "--version"], capture_output=True, check=False)
                deps["rocm"] = True
            except Exception:
                deps["rocm"] = False

        return deps

    def clone_llama_cpp(self, force: bool = False) -> bool:
        """Clone llama.cpp repository."""
        return clone_llama_cpp(config=self.config, force=force)

    def build_llama_cpp(self) -> bool:
        """Build llama.cpp with auto-detected GPU support."""
        return build_llama_cpp(config=self.config)

    def _get_hf_snapshot(self, repo_id: str, revision: str = "main"):
        """
        Get repo snapshot using local cache + SHA validation.

        Cache behavior:
        - miss -> fetch full snapshot and store
        - hit -> fetch remote SHA and refresh only if SHA changed
        - if SHA check fails, fall back to cached snapshot
        """
        cached = self.hf_cache.get(repo_id=repo_id, revision=revision)
        if cached is None:
            self._record_cache_event("miss")
            print(f"🧠 HF cache miss: {repo_id}@{revision} (fetching snapshot)")
            snap = self.hf.get_snapshot(repo_id=repo_id, revision=revision)
            self.hf_cache.put(snap)
            return snap

        try:
            remote_sha = self.hf.get_repo_sha(repo_id=repo_id, revision=revision)
        except Exception:
            self._record_cache_event("fallback")
            print(f"🧠 HF cache fallback: {repo_id}@{revision} (SHA check failed, using cached snapshot)")
            self.hf_cache.touch(repo_id=repo_id, revision=revision)
            return cached.snapshot

        cached_sha = cached.sha or cached.snapshot.sha
        sha_changed = bool(remote_sha) and remote_sha != cached_sha
        sha_missing_locally = bool(remote_sha) and not cached_sha

        if sha_changed or sha_missing_locally:
            self._record_cache_event("refresh")
            print(f"🧠 HF cache refresh: {repo_id}@{revision} (SHA changed)")
            snap = self.hf.get_snapshot(repo_id=repo_id, revision=revision)
            self.hf_cache.put(snap)
            return snap

        self._record_cache_event("hit")
        print(f"🧠 HF cache hit: {repo_id}@{revision} (SHA unchanged)")
        self.hf_cache.touch(repo_id=repo_id, revision=revision)
        return cached.snapshot

    def list_huggingface_files(self, repo_id: str):
        """List available files in a HuggingFace repo (GGUF + mmproj)."""
        repo_id = self.normalize_hf_repo_id(repo_id)
        snap = self._get_hf_snapshot(repo_id=repo_id, revision="main")

        print(f"\n📦 {repo_id}")
        if snap.pipeline_tag:
            print(f"   Type: {snap.pipeline_tag}")
        if snap.tags:
            print(f"   Tags: {', '.join(snap.tags[:8])}{'...' if len(snap.tags) > 8 else ''}")
        if snap.sha:
            print(f"   SHA: {snap.sha[:12]}")

        ggufs = snap.gguf_files
        mmprojs = snap.mmproj_files

        if ggufs:
            print("\n📋 Available GGUF files:")
            for index, file in enumerate(ggufs[:10], 1):
                size_str = f" ({file.size // 1024 // 1024} MB)" if file.size else ""
                print(f"  {index}. {file.path}{size_str}")
            if len(ggufs) > 10:
                print(f"  ... and {len(ggufs) - 10} more")
        else:
            print("\n❌ No GGUF files found.")

        if mmprojs:
            print("\n🖼️  MMproj files available:")
            for file in mmprojs:
                size_str = f" ({file.size // 1024 // 1024} MB)" if file.size else ""
                print(f"  • {file.path}{size_str}")

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

        ggufs = snap.gguf_files
        if not ggufs:
            print(f"❌ No GGUF files found in {repo_id}")
            return False

        if filename:
            match = next((file for file in snap.files if file.path == filename), None)
            if not match:
                print(f"❌ File not found in repo: {filename}")
                print("Tip: use --list to see available files.")
                return False
            model_file = match
            mmproj_file = snap.mmproj_files[0] if (download_mmproj and snap.mmproj_files) else None
        else:
            preferred_quants: List[str] = []
            if quant_preference:
                preferred_quants.append(quant_preference.upper())
            preferred_quants.extend(DEFAULT_QUANT_RANKING)
            resolved = resolve_download(snap, preferred_quants=preferred_quants)
            model_file = resolved.model_file
            mmproj_file = resolved.mmproj_file if download_mmproj else None
            print(f"\n📝 Auto-selected: {model_file.path}")
            if quant_preference:
                print(f"   Quant preference: {quant_preference.upper()}")

        models_dir = str(self.config.paths.models_dir)
        model_local_path = Path(
            self.hf.download_file(repo_id, model_file.path, revision=snap.revision, local_dir=models_dir)
        )

        mmproj_local_path: Optional[Path] = None
        if mmproj_file:
            print(f"🖼️  Downloading MMproj: {mmproj_file.path}")
            mmproj_local_path = Path(
                self.hf.download_file(repo_id, mmproj_file.path, revision=snap.revision, local_dir=models_dir)
            )

        self.registry.register_model(
            path=model_local_path,
            origin="huggingface",
            mmproj_path=mmproj_local_path,
            repo={
                "repo_id": repo_id,
                "revision": snap.revision,
                "sha": snap.sha,
                "source_url": f"https://huggingface.co/{repo_id}",
            },
            derived=derive_model_metadata(repo_id=repo_id, model_file=model_file),
            save=True,
        )

        if mmproj_local_path:
            self.registry.register_mmproj(
                path=mmproj_local_path,
                origin="huggingface",
                for_models=[model_local_path.name],
                repo={
                    "repo_id": repo_id,
                    "revision": snap.revision,
                    "sha": snap.sha,
                    "source_url": f"https://huggingface.co/{repo_id}",
                },
                save=True,
            )

        print("\n✅ Download complete!")
        print(f"   Model: {model_local_path.name}")
        if mmproj_local_path:
            print(f"   MMproj: {mmproj_local_path.name}")

        print("\n📋 To start the server:")
        print(f"   server-start {model_local_path.name}")

        return True

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
            print("   from ai_stack.setup import SetupManager")
            print("   manager = SetupManager()")
            print("   server = manager.start_server('models/your-model.gguf')")
            print("   # Or via CLI: server-start your-model.gguf")

        print("\n2. Use the LLM client:")
        print("   from ai_stack.llm import create_client")
        print("   client = create_client()")
        print("   response = client.chat([{'role': 'user', 'content': 'Hello'}])")

        return True


__all__ = ["SetupManager"]
