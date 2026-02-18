"""
AI Stack Setup Manager - Handles installation and configuration
"""
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from ai_stack.huggingface.client import HuggingFaceClient
from ai_stack.huggingface.cache import HuggingFaceSnapshotCache
from ai_stack.huggingface.metadata import derive_model_metadata
from ai_stack.huggingface.resolver import DEFAULT_QUANT_RANKING, resolve_download
import requests

from ai_stack.models.registry import ModelRegistry
from .config import config

class SetupManager:
    """Manages AI Stack setup without .env files"""
    
    def __init__(self):
        self.config = config
        self.registry = ModelRegistry(models_dir=self.config.paths.models_dir)
        self.registry.ensure_manifest()
        self.hf = HuggingFaceClient()
        self.hf_cache = HuggingFaceSnapshotCache(
            cache_path=self.config.paths.script_dir / "huggingface" / "cache.json"
        )
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
                import shutil  # Add this import
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
        snap = self._get_hf_snapshot(repo_id=repo_id, revision="main")

        print(f"\n📦 {repo_id}")
        if snap.pipeline_tag:
            print(f"   Type: {snap.pipeline_tag}")
        if snap.tags:
            # keep it short
            print(f"   Tags: {', '.join(snap.tags[:8])}{'...' if len(snap.tags) > 8 else ''}")
        if snap.sha:
            print(f"   SHA: {snap.sha[:12]}")

        ggufs = snap.gguf_files
        mmprojs = snap.mmproj_files

        if ggufs:
            print(f"\n📋 Available GGUF files:")
            for i, f in enumerate(ggufs[:10], 1):
                size_str = f" ({f.size // 1024 // 1024} MB)" if f.size else ""
                print(f"  {i}. {f.path}{size_str}")
            if len(ggufs) > 10:
                print(f"  ... and {len(ggufs) - 10} more")
        else:
            print("\n❌ No GGUF files found.")

        if mmprojs:
            print(f"\n🖼️  MMproj files available:")
            for f in mmprojs:
                size_str = f" ({f.size // 1024 // 1024} MB)" if f.size else ""
                print(f"  • {f.path}{size_str}")

    
    def download_from_huggingface(
        self,
        repo_id: str,
        filename: Optional[str] = None,
        download_mmproj: bool = False,
        quant_preference: Optional[str] = None,
    ) -> bool:
        print(f"🔍 Fetching info for {repo_id}...")
        snap = self._get_hf_snapshot(repo_id=repo_id, revision="main")

        ggufs = snap.gguf_files
        if not ggufs:
            print(f"❌ No GGUF files found in {repo_id}")
            return False

        # Decide model file
        if filename:
            # user specified exact path
            match = next((f for f in snap.files if f.path == filename), None)
            if not match:
                print(f"❌ File not found in repo: {filename}")
                print("Tip: use --list to see available files.")
                return False
            model_file = match
            mmproj_file = None
            if download_mmproj:
                mmproj_file = snap.mmproj_files[0] if snap.mmproj_files else None
        else:
            preferred_quants: List[str] = []
            if quant_preference:
                preferred_quants.append(quant_preference.upper())
            preferred_quants.extend(DEFAULT_QUANT_RANKING)
            resolved = resolve_download(
                snap,
                preferred_quants=preferred_quants,
            )
            model_file = resolved.model_file
            mmproj_file = resolved.mmproj_file if download_mmproj else None
            print(f"\n📝 Auto-selected: {model_file.path}")
            if quant_preference:
                print(f"   Quant preference: {quant_preference.upper()}")

        # Download model into your local models dir
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

        # Register into manifest (registry)
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

        print(f"\n✅ Download complete!")
        print(f"   Model: {model_local_path.name}")
        if mmproj_local_path:
            print(f"   MMproj: {mmproj_local_path.name}")

        print(f"\n📋 To start the server:")
        print(f"   server-start {model_local_path.name}")

        return True

    def start_server(self, 
                    model_path: Optional[str] = None,
                    mmproj_path: Optional[str] = None) -> subprocess.Popen:
        """Start llama.cpp server"""
        
        if not self.config.is_llama_built:
            raise RuntimeError("llama.cpp is not built. Run setup() first.")
        
        # Require explicit model path - no auto-selection
        if not model_path:
            raise ValueError(
                "No model specified. You must provide a model path.\n"
                "Example: manager.start_server('models/my-model.gguf')"
            )
        
        model_path = Path(model_path)
        if not model_path.exists():
            # Try relative to models_dir
            alt_path = self.config.paths.models_dir / model_path
            if alt_path.exists():
                model_path = alt_path
            else:
                # If not found, scan models dir to ensure manifest is up-to-date
                self.registry.scan_models_dir()
                model_names = [m["name"] for m in self.registry.manifest.get("models", [])]

                if model_names:
                    model_list = "\n  • ".join(model_names[:5])
                    msg = (
                        f"Model not found: {model_path}\n"
                        f"Available models in {self.config.paths.models_dir}:\n  • {model_list}"
                    )
                    if len(model_names) > 5:
                        msg += f"\n  ... and {len(model_names) - 5} more"
                else:
                    msg = f"Model not found: {model_path}\nNo models available in {self.config.paths.models_dir}"
            
                raise FileNotFoundError(msg)
        
        # Auto-detect MMproj from manifest if not provided
        if not mmproj_path:
            mmproj = self.registry.get_mmproj_for_model(model_path)
            if mmproj:
                print(f"📎 Auto-detected MMproj: {mmproj.name}")
                mmproj_path = str(mmproj)
        
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
            print("   # Example: download-model https://huggingface.co/TheBloke/Llama-2-7B-GGUF/resolve/main/llama-2-7b.Q4_K_M.gguf")
        else:
            print("1. Start server with a specific model:")
            print("   from ai_stack.setup import SetupManager")
            print("   manager = SetupManager()")
            print("   server = manager.start_server('models/your-model.gguf')")
            print("   # Or via CLI: server-start your-model.gguf")
    
        print(f"\n2. Use the LLM client:")
        print(f"   from ai_stack.llm import create_client")
        print(f"   client = create_client()")
        print(f"   response = client.chat([{{'role': 'user', 'content': 'Hello'}}])")
        
        return True
