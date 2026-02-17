"""
AI Stack Setup Manager - Handles installation and configuration
"""
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from .huggingface import HFModelManager, CachedHFModelManager
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
    
class SetupManager:
    def __init__(self):
        self.config = config
        self.hf_manager = HFModelManager(config.paths.models_dir)
    
    def list_huggingface_files(self, repo_id: str):
        """List available files in a HuggingFace repo"""
        files = self.hf_manager.find_gguf_files(repo_id)
        mmproj = self.hf_manager.find_mmproj_files(repo_id)
        
        # Get model info
        info = self.hf_manager.get_model_metadata(repo_id)
        if info:
            print(f"\n📦 {repo_id}")
            print(f"   Type: {info['pipeline_tag'] or 'unknown'}")
            if info['is_vision']:
                print(f"   🖼️  Vision model")
            print(f"   Downloads: {info['downloads']:,}")
            print(f"   Likes: {info['likes']}")
        
        if files:
            print(f"\n📋 Available GGUF files:")
            for i, f in enumerate(files[:10], 1):
                size = self.hf_manager.get_file_size(repo_id, f)
                size_str = f" ({size // 1024 // 1024} MB)" if size else ""
                is_mmproj = " (MMproj)" if 'mmproj' in f.lower() else ""
                print(f"  {i}. {f}{size_str}{is_mmproj}")
            
            if len(files) > 10:
                print(f"  ... and {len(files) - 10} more")
        
        if mmproj:
            print(f"\n🖼️  MMproj files available:")
            for f in mmproj:
                print(f"  • {f}")
    
    def download_from_huggingface(self, 
                                 repo_id: str, 
                                 filename: Optional[str] = None,
                                 download_mmproj: bool = False) -> bool:
        """Download model from HuggingFace"""
        
        print(f"🔍 Fetching info for {repo_id}...")
        info = self.hf_manager.get_model_metadata(repo_id)
        
        if not info:
            return False
        
        print(f"  Type: {info['pipeline_tag'] or 'unknown'}")
        if info['is_vision']:
            print(f"  🖼️  Vision model detected")
        
        # Get available files
        files = self.hf_manager.find_gguf_files(repo_id)
        if not files:
            print(f"❌ No GGUF files found in {repo_id}")
            return False
        
        # Select file
        if not filename:
            # Auto-select: prefer non-mmproj files
            candidates = [f for f in files if 'mmproj' not in f.lower()]
            filename = candidates[0] if candidates else files[0]
            print(f"\n📝 Auto-selected: {filename}")
        
        # Find MMproj if requested
        mmproj_filename = None
        if download_mmproj or info['is_vision']:
            mmproj_filename = self.hf_manager.suggest_mmproj(repo_id, filename)
            if mmproj_filename:
                print(f"🖼️  Found MMproj: {mmproj_filename}")
        
        # Download
        result = self.hf_manager.download_model_with_mmproj(
            repo_id,
            model_filename=filename,
            mmproj_filename=mmproj_filename
        )
        
        if result["model"]:
            # Extract info for manifest
            model_info = self.hf_manager.extract_model_info(repo_id, filename)
            
            # Add to manifest
            self.config.add_model_to_manifest(
                model_path=result["model"],
                source_url=f"https://huggingface.co/{repo_id}",
                mmproj_path=result["mmproj"],
                family=model_info["family"],
                metadata={
                    "repo": repo_id,
                    "pipeline": info['pipeline_tag'],
                    "is_vision": info['is_vision']
                }
            )
            
            if result["mmproj"]:
                # Find all models this MMproj works with
                base_name = filename.split('.Q')[0] if '.Q' in filename else filename.rsplit('.', 1)[0]
                for_models = [
                    f.name for f in self.config.paths.models_dir.glob(f"{base_name}*.gguf")
                    if 'mmproj' not in f.name.lower()
                ]
                
                self.config.add_mmproj_to_manifest(
                    mmproj_path=result["mmproj"],
                    for_models=for_models,
                    source_url=f"https://huggingface.co/{repo_id}"
                )
            
            print(f"\n✅ Download complete!")
            print(f"   Model: {result['model'].name}")
            if result["mmproj"]:
                print(f"   MMproj: {result['mmproj'].name}")
            
            # Show next steps
            print(f"\n📋 To start the server:")
            print(f"   server-start {result['model'].name}")
            
            return True
        
        return False

    def _detect_model_family(self, filename: str) -> str:
        """Simple family detection from filename"""
        name = filename.replace('.gguf', '')
        
        # Remove quantization
        if '.Q' in name:
            name = name.split('.Q')[0]
        
        # Remove common suffixes
        for suffix in ['.instruct', '-instruct', '_instruct',
                    '.chat', '-chat', '_chat',
                    '.base', '-base', '_base',
                    '.vision', '-vision', '_vision']:
            if suffix in name.lower():
                name = name[:name.lower().index(suffix)]

        return name
    
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
                # Show available models to help user
                models = self.config.get_available_models()
                if models:
                    model_list = "\n  • ".join([m['name'] for m in models[:5]])
                    msg = (
                        f"Model not found: {model_path}\n"
                        f"Available models in {self.config.paths.models_dir}:\n  • {model_list}"
                    )
                    if len(models) > 5:
                        msg += f"\n  ... and {len(models) - 5} more"
                else:
                    msg = f"Model not found: {model_path}\nNo models available in {self.config.paths.models_dir}"
            
                raise FileNotFoundError(msg)
        
        # Auto-detect MMproj from manifest if not provided
        if not mmproj_path:
            mmproj = self.config.get_mmproj_for_model(model_path)
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