"""AI Stack setup and orchestration manager."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ai_stack.core.config import config
from ai_stack.core.logging import emit_event
from ai_stack.huggingface.cache import HuggingFaceSnapshotCache
from ai_stack.huggingface.client import HuggingFaceClient, RepoSnapshot
from ai_stack.llama.build import build_llama_cpp, clone_llama_cpp
from ai_stack.llama.server import start_llama_server
from ai_stack.models.registry import ModelRegistry
from . import hf_downloads


@dataclass
class SetupResult:
    success: bool
    missing_critical: List[str]
    clone_ok: bool
    build_ok: bool
    has_models: bool
    models_dir: Path


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
        self._last_cache_event: Optional[str] = None

    def _record_cache_event(self, event: str) -> None:
        if event in self.hf_cache_diagnostics:
            self.hf_cache_diagnostics[event] += 1
        emit_event("hf.cache.event", cache_event=event)

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

    @staticmethod
    def format_cache_event(event: Optional[str], repo_id: str, revision: str) -> Optional[str]:
        if event == "miss":
            return f"🧠 HF cache miss: {repo_id}@{revision} (fetching snapshot)"
        if event == "hit":
            return f"🧠 HF cache hit: {repo_id}@{revision} (SHA unchanged)"
        if event == "refresh":
            return f"🧠 HF cache refresh: {repo_id}@{revision} (SHA changed)"
        if event == "fallback":
            return f"🧠 HF cache fallback: {repo_id}@{revision} (SHA check failed, using cached snapshot)"
        return None

    def check_dependencies(self) -> Dict[str, bool]:
        """Check system dependencies."""
        emit_event("setup.dependencies.check.start")
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

        missing = [name for name, ok in deps.items() if not ok]
        emit_event("setup.dependencies.check.complete", missing=missing, ok=not missing)
        return deps

    def clone_llama_cpp(self, force: bool = False) -> bool:
        """Clone llama.cpp repository."""
        paths = getattr(self.config, "paths", None)
        llama_cpp_dir = getattr(paths, "llama_cpp_dir", None)
        emit_event("llama.clone.start", force=force, target_dir=str(llama_cpp_dir) if llama_cpp_dir else None)
        ok = clone_llama_cpp(config=self.config, force=force)
        emit_event("llama.clone.complete", ok=ok)
        return ok

    def build_llama_cpp(self) -> bool:
        """Build llama.cpp with auto-detected GPU support."""
        gpu = getattr(self.config, "gpu", None)
        emit_event("llama.build.start", vendor=getattr(gpu, "vendor", None), target=getattr(gpu, "target", None))
        ok = build_llama_cpp(config=self.config)
        emit_event("llama.build.complete", ok=ok)
        return ok

    def _get_hf_snapshot(self, repo_id: str, revision: str = "main") -> RepoSnapshot:
        emit_event("hf.snapshot.fetch.start", repo_id=repo_id, revision=revision)
        result = hf_downloads.get_hf_snapshot(
            hf_client=self.hf,
            hf_cache=self.hf_cache,
            record_cache_event=self._record_cache_event,
            repo_id=repo_id,
            revision=revision,
        )
        self._last_cache_event = result.cache_event
        emit_event(
            "hf.snapshot.fetch.complete",
            repo_id=repo_id,
            revision=revision,
            cache_event=result.cache_event,
        )
        return result.snapshot

    def list_huggingface_files(self, repo_id: str) -> hf_downloads.HfFileListResult:
        """List available files in a HuggingFace repo (GGUF + mmproj)."""
        emit_event("hf.list.start", repo_input=repo_id)
        repo_id = self.normalize_hf_repo_id(repo_id)
        snap = self._get_hf_snapshot(repo_id=repo_id, revision="main")
        result = hf_downloads.list_huggingface_files(snapshot=snap)
        result.cache_event = self._last_cache_event
        emit_event(
            "hf.list.complete",
            repo_id=repo_id,
            gguf_count=len(result.gguf_files),
            mmproj_count=len(result.mmproj_files),
            cache_event=result.cache_event,
        )
        return result

    def download_from_huggingface(
        self,
        repo_id: str,
        filename: Optional[str] = None,
        download_mmproj: bool = False,
        quant_preference: Optional[str] = None,
    ) -> hf_downloads.HfDownloadResult:
        emit_event(
            "hf.download.start",
            repo_input=repo_id,
            filename=filename,
            download_mmproj=download_mmproj,
            quant_preference=quant_preference,
        )
        repo_id = self.normalize_hf_repo_id(repo_id)
        snap = self._get_hf_snapshot(repo_id=repo_id, revision="main")
        result = hf_downloads.download_from_huggingface(
            config=self.config,
            registry=self.registry,
            hf_client=self.hf,
            snapshot=snap,
            repo_id=repo_id,
            filename=filename,
            download_mmproj=download_mmproj,
            quant_preference=quant_preference,
        )
        result.cache_event = self._last_cache_event
        emit_event(
            "hf.download.complete",
            repo_id=repo_id,
            ok=result.success,
            selected_model_file=result.selected_model_file,
            has_mmproj=bool(result.mmproj_path),
            cache_event=result.cache_event,
            error=result.error,
        )
        return result

    def start_server(
        self,
        model_path: Optional[str] = None,
        mmproj_path: Optional[str] = None,
        stdout=None,
        stderr=None,
    ):
        """Start llama.cpp server."""
        emit_event("server.start.requested", model_path=model_path, mmproj_path=mmproj_path)
        return start_llama_server(
            config=self.config,
            registry=self.registry,
            model_path=model_path,
            mmproj_path=mmproj_path,
            stdout=stdout,
            stderr=stderr,
        )

    def setup(self) -> SetupResult:
        """Complete setup process and return structured result."""
        emit_event("setup.run.start")
        deps = self.check_dependencies()

        missing_critical = [dep for dep, installed in deps.items() if not installed and dep in ["git", "cmake", "make"]]
        if missing_critical:
            emit_event("setup.run.complete", ok=False, reason="missing_critical", missing_critical=missing_critical)
            return SetupResult(
                success=False,
                missing_critical=missing_critical,
                clone_ok=False,
                build_ok=False,
                has_models=self.config.has_models,
                models_dir=self.config.paths.models_dir,
            )

        clone_ok = self.clone_llama_cpp()
        if not clone_ok:
            emit_event("setup.run.complete", ok=False, reason="clone_failed")
            return SetupResult(
                success=False,
                missing_critical=[],
                clone_ok=False,
                build_ok=False,
                has_models=self.config.has_models,
                models_dir=self.config.paths.models_dir,
            )

        build_ok = self.build_llama_cpp()
        if not build_ok:
            emit_event("setup.run.complete", ok=False, reason="build_failed")
            return SetupResult(
                success=False,
                missing_critical=[],
                clone_ok=True,
                build_ok=False,
                has_models=self.config.has_models,
                models_dir=self.config.paths.models_dir,
            )

        result = SetupResult(
            success=True,
            missing_critical=[],
            clone_ok=True,
            build_ok=True,
            has_models=self.config.has_models,
            models_dir=self.config.paths.models_dir,
        )
        emit_event("setup.run.complete", ok=True, has_models=result.has_models)
        return result


__all__ = ["SetupManager", "SetupResult"]
