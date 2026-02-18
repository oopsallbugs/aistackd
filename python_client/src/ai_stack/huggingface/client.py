from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from huggingface_hub import HfApi, hf_hub_download


@dataclass(frozen=True)
class RepoFile:
    path: str
    size: Optional[int] = None
    lfs: Optional[Dict[str, Any]] = None  # may contain oid/size/etc depending on hub response


@dataclass(frozen=True)
class RepoSnapshot:
    repo_id: str
    revision: str
    sha: Optional[str]
    last_modified: Optional[str]
    pipeline_tag: Optional[str]
    tags: List[str]
    library_name: Optional[str]
    files: List[RepoFile]

    @property
    def gguf_files(self) -> List[RepoFile]:
        return [f for f in self.files if f.path.lower().endswith(".gguf") and "mmproj" not in f.path.lower()]

    @property
    def mmproj_files(self) -> List[RepoFile]:
        return [f for f in self.files if f.path.lower().endswith(".gguf") and "mmproj" in f.path.lower()]


class HuggingFaceClient:
    """
    Responsibilities:
    - Fetch repo metadata + file listing (with sizes) via model_info(...)
    - Download a specific file via hf_hub_download(...)

    Not responsible for:
    - picking "best" quant
    - pairing mmproj
    - writing manifest
    - caching (we add HFCache separately)
    """

    def __init__(self, token: Optional[str] = None):
        self.api = HfApi(token=token)
        self.token = token

    def get_snapshot(self, repo_id: str, revision: str = "main") -> RepoSnapshot:
        """
        Fetch metadata + file listing in a single call.

        Uses:
        - files_metadata=True to get size/LFS info
        """
        info = self.api.model_info(
            repo_id=repo_id,
            revision=revision,
            files_metadata=True,
        )

        files: List[RepoFile] = []
        siblings = getattr(info, "siblings", None) or []
        for s in siblings:
            # Each sibling is usually a ModelFile with fields like rfilename, size, lfs
            path = getattr(s, "rfilename", None) or getattr(s, "path", None) or ""
            if not path:
                continue
            size = getattr(s, "size", None)
            lfs = getattr(s, "lfs", None)
            files.append(RepoFile(path=path, size=size, lfs=lfs))

        tags = list(getattr(info, "tags", None) or [])


        # last_modified naming differs across versions; handle both
        last_modified = getattr(info, "last_modified", None) or getattr(info, "lastModified", None)

        return RepoSnapshot(
            repo_id=repo_id,
            revision=revision,
            sha=getattr(info, "sha", None),
            last_modified=str(last_modified) if last_modified else None,
            pipeline_tag=getattr(info, "pipeline_tag", None),
            tags=tags,
            library_name=getattr(info, "library_name", None),
            files=files,
        )

    def get_repo_sha(self, repo_id: str, revision: str = "main") -> Optional[str]:
        """
        Fetch only the current revision SHA for cache validation.
        """
        info = self.api.model_info(
            repo_id=repo_id,
            revision=revision,
            files_metadata=False,
        )
        return getattr(info, "sha", None)

    def download_file(
        self,
        repo_id: str,
        filename: str,
        revision: str = "main",
        local_dir: Optional[str] = None,
    ) -> str:
        """
        Download a single file from a repo and return the local file path.

        If local_dir is provided, huggingface_hub will place the file there
        (still uses the cache under the hood).
        """
        return hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            token=self.token,
            local_dir=local_dir,
        )
