"""
HuggingFace Hub integration for AI Stack
Handles model discovery, downloading, and metadata extraction
"""
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
import json, re
from datetime import datetime
import fnmatch

# Base imports that always work
from huggingface_hub import (
    model_info,
    list_repo_files,
    hf_hub_download,
    HfFileSystem,
)

# Try to import specific exceptions, with fallbacks
try:
    from huggingface_hub import RepositoryNotFoundError
except ImportError:
    # Define a placeholder if not available
    class RepositoryNotFoundError(Exception):
        pass

try:
    from huggingface_hub import GatedRepoError
except ImportError:
    class GatedRepoError(Exception):
        pass

try:
    from huggingface_hub import RevisionNotFoundError
except ImportError:
    class RevisionNotFoundError(Exception):
        pass

class HFModelManager:
    """Manages HuggingFace model interactions"""
    
    def __init__(self, models_dir: Path):
        self.models_dir = Path(models_dir)
        self.cache_dir = self.models_dir / "hub_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Optional: Initialize filesystem for advanced operations
        self.fs = HfFileSystem()
    
    def get_model_metadata(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive model metadata from HuggingFace"""
        try:
            info = model_info(repo_id)
            
            # Determine model capabilities
            pipeline = info.pipeline_tag or ""
            is_vision = any([
                pipeline in ["image-to-text", "image-classification", "object-detection"],
                "vision" in str(info.tags).lower(),
                "multimodal" in str(info.tags).lower(),
                "clip" in str(info.tags).lower(),
            ])
            
            is_text = any([
                pipeline in ["text-generation", "text-classification", "feature-extraction"],
                "llm" in str(info.tags).lower(),
            ])
            
            return {
                "id": info.modelId,
                "author": info.author,
                "pipeline_tag": pipeline,
                "is_vision": is_vision,
                "is_text": is_text,
                "is_multimodal": "multimodal" in str(info.tags).lower(),
                "library": info.library_name,
                "tags": info.tags,
                "config": info.config,
                "downloads": info.downloads,
                "likes": info.likes,
                "created_at": info.created_at.isoformat() if info.created_at else None,
                "private": info.private,
                "gated": info.gated,
            }
            
        except Exception as e:
            # Handle based on error message since exceptions might not exist
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                print(f"❌ Repository not found: {repo_id}")
            elif "gated" in error_str or "private" in error_str:
                print(f"❌ Repository is gated/private (requires login): {repo_id}")
            else:
                print(f"❌ Error fetching model info: {e}")
        
        return None
    
    def list_repo_files(self, repo_id: str, pattern: str = None) -> List[str]:
        """List files in a HuggingFace repository"""
        try:
            files = list_repo_files(repo_id)
            
            if pattern:
                files = [f for f in files if fnmatch.fnmatch(f, pattern)]
            
            return sorted(files)
            
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                print(f"❌ Repository not found: {repo_id}")
            elif "gated" in error_str or "private" in error_str:
                print(f"❌ Repository is gated/private (requires login): {repo_id}")
            else:
                print(f"❌ Error listing files: {e}")
            return []
    
    def find_gguf_files(self, repo_id: str) -> List[str]:
        """Find all GGUF files in a repository"""
        return self.list_repo_files(repo_id, "*.gguf")
    
    def find_mmproj_files(self, repo_id: str) -> List[str]:
        """Find all MMproj files in a repository"""
        files = self.list_repo_files(repo_id)
        return [f for f in files if 'mmproj' in f.lower() and f.endswith('.gguf')]
    
    def get_file_size(self, repo_id: str, filename: str) -> Optional[int]:
        """Get size of a file in the repository"""
        try:
            file_info = self.fs.info(f"{repo_id}/{filename}")
            return file_info.get("size")
        except:
            return None
    
    def download_file(self, 
                     repo_id: str, 
                     filename: str,
                     force_download: bool = False) -> Optional[Path]:
        """Download a specific file from HuggingFace"""
        try:
            local_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                cache_dir=self.cache_dir,
                local_dir=self.models_dir,
                local_dir_use_symlinks=True,
                resume=True,
                force_download=force_download,
                force_filename=filename
            )
            
            return Path(local_path)
            
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                print(f"❌ File not found: {filename} in {repo_id}")
            elif "gated" in error_str or "private" in error_str:
                print(f"❌ Repository is gated/private (requires login): {repo_id}")
            else:
                print(f"❌ Error downloading {filename}: {e}")
            return None
    
    def download_model_with_mmproj(self, 
                                   repo_id: str,
                                   model_filename: Optional[str] = None,
                                   mmproj_filename: Optional[str] = None) -> Dict[str, Optional[Path]]:
        """Download model and optionally its MMproj file"""
        result = {"model": None, "mmproj": None}
        
        # List available files
        gguf_files = self.find_gguf_files(repo_id)
        mmproj_files = self.find_mmproj_files(repo_id)
        
        if not gguf_files:
            print(f"❌ No GGUF files found in {repo_id}")
            return result
        
        # Select model file
        if not model_filename:
            # Auto-select: prefer non-mmproj files
            candidates = [f for f in gguf_files if 'mmproj' not in f.lower()]
            if candidates:
                model_filename = candidates[0]
            else:
                model_filename = gguf_files[0]
            print(f"📝 Auto-selected: {model_filename}")
        
        # Download model
        print(f"📥 Downloading model: {model_filename}")
        model_path = self.download_file(repo_id, model_filename)
        if model_path:
            result["model"] = model_path
        
        # Handle MMproj
        if mmproj_files and mmproj_filename:
            print(f"📥 Downloading MMproj: {mmproj_filename}")
            mmproj_path = self.download_file(repo_id, mmproj_filename)
            if mmproj_path:
                result["mmproj"] = mmproj_path
        elif mmproj_files and not mmproj_filename:
            # Auto-select MMproj if requested elsewhere
            pass
        
        return result
    
    def extract_model_info(self, repo_id: str, filename: str) -> Dict[str, Any]:
        """Extract structured info from repo and filename"""
        # Get metadata from HuggingFace
        metadata = self.get_model_metadata(repo_id) or {}
        
        # Parse filename
        name = Path(filename).stem
        
        # Extract quantization if present
        quantization = None
        if '.Q' in filename:
            match = re.search(r'\.(Q[0-9]_[A-Z_]+)', filename)
            if match:
                quantization = match.group(1)
        
        # Extract size if present (7B, 13B, 70B)
        size_match = re.search(r'(\d+\.?\d*B)', name, re.IGNORECASE)
        size = size_match.group(1) if size_match else None
        
        # Determine base family
        if size:
            base = name.split(f'.{size}')[0] if f'.{size}' in name else name.split(f'-{size}')[0]
        else:
            base = name.split('.Q')[0] if '.Q' in name else name
        
        return {
            "repo_id": repo_id,
            "filename": filename,
            "family": base,
            "size": size,
            "quantization": quantization,
            "is_mmproj": 'mmproj' in filename.lower(),
            "is_vision": metadata.get("is_vision", False),
            "is_text": metadata.get("is_text", False),
            "pipeline": metadata.get("pipeline_tag"),
            "metadata": metadata,
        }
    
    def suggest_mmproj(self, repo_id: str, model_filename: str) -> Optional[str]:
        """Suggest an MMproj file for a given model"""
        mmproj_files = self.find_mmproj_files(repo_id)
        if not mmproj_files:
            return None
        
        # Extract base model name
        base_name = Path(model_filename).stem.split('.Q')[0]
        
        # Try to find matching MMproj
        for f in mmproj_files:
            if base_name in f:
                return f
        
        return mmproj_files[0] if mmproj_files else None

# Optional: Add a simple cache for metadata to avoid repeated API calls
class CachedHFModelManager(HFModelManager):
    def __init__(self, models_dir: Path, cache_file: Optional[Path] = None):
        super().__init__(models_dir)
        self.cache_file = cache_file or models_dir / "hf_metadata_cache.json"
        self.metadata_cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_cache(self):
        with open(self.cache_file, 'w') as f:
            json.dump(self.metadata_cache, f, indent=2)
    
    def get_model_metadata(self, repo_id: str, force_refresh: bool = False) -> Optional[Dict]:
        """Cached version of get_model_metadata"""
        if not force_refresh and repo_id in self.metadata_cache:
            return self.metadata_cache[repo_id]
        
        metadata = super().get_model_metadata(repo_id)
        if metadata:
            self.metadata_cache[repo_id] = metadata
            self._save_cache()
        
        return metadata