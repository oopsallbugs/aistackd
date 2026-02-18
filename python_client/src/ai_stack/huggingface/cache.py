from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from ai_stack.huggingface.client import RepoFile, RepoSnapshot


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CachedRepoSnapshot:
    key: str
    sha: Optional[str]
    last_checked: str
    snapshot: RepoSnapshot


class HuggingFaceSnapshotCache:
    """
    Stores serialized RepoSnapshot entries by repo_id@revision.

    Cache file schema:
    {
      "schema_version": 1,
      "updated_at": "...",
      "repos": {
        "repo_id@revision": {
          "sha": "...",
          "last_checked": "...",
          "snapshot": { ... }
        }
      }
    }
    """

    SCHEMA_VERSION = 1

    def __init__(self, cache_path: Union[str, Path]):
        self.cache_path = Path(cache_path)
        self.data: Dict[str, Any] = {}

    def ensure_cache(self) -> Dict[str, Any]:
        if self.data:
            return self.data
        self.data = self._load_or_create()
        return self.data

    @staticmethod
    def make_key(repo_id: str, revision: str) -> str:
        return f"{repo_id}@{revision}"

    def get(self, repo_id: str, revision: str = "main") -> Optional[CachedRepoSnapshot]:
        data = self.ensure_cache()
        key = self.make_key(repo_id, revision)
        raw = (data.get("repos") or {}).get(key)
        if not raw:
            return None

        snapshot_raw = raw.get("snapshot")
        if not isinstance(snapshot_raw, dict):
            return None

        try:
            snapshot = self._deserialize_snapshot(snapshot_raw)
        except Exception:
            return None

        return CachedRepoSnapshot(
            key=key,
            sha=raw.get("sha"),
            last_checked=raw.get("last_checked") or _utc_now_iso(),
            snapshot=snapshot,
        )

    def put(self, snapshot: RepoSnapshot, last_checked: Optional[str] = None) -> None:
        data = self.ensure_cache()
        key = self.make_key(snapshot.repo_id, snapshot.revision)
        repos = data.setdefault("repos", {})
        repos[key] = {
            "sha": snapshot.sha,
            "last_checked": last_checked or _utc_now_iso(),
            "snapshot": self._serialize_snapshot(snapshot),
        }
        self.save()

    def touch(self, repo_id: str, revision: str = "main", last_checked: Optional[str] = None) -> None:
        data = self.ensure_cache()
        key = self.make_key(repo_id, revision)
        raw = (data.get("repos") or {}).get(key)
        if not raw:
            return
        raw["last_checked"] = last_checked or _utc_now_iso()
        self.save()

    def save(self) -> None:
        data = self.ensure_cache()
        data["schema_version"] = self.SCHEMA_VERSION
        data["updated_at"] = _utc_now_iso()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_or_create(self) -> Dict[str, Any]:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("schema_version") == self.SCHEMA_VERSION:
                    data.setdefault("repos", {})
                    data.setdefault("updated_at", None)
                    return data
            except (OSError, json.JSONDecodeError):
                pass

        data = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": _utc_now_iso(),
            "repos": {},
        }
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data

    def _serialize_snapshot(self, snapshot: RepoSnapshot) -> Dict[str, Any]:
        return {
            "repo_id": snapshot.repo_id,
            "revision": snapshot.revision,
            "sha": snapshot.sha,
            "last_modified": snapshot.last_modified,
            "pipeline_tag": snapshot.pipeline_tag,
            "tags": list(snapshot.tags),
            "library_name": snapshot.library_name,
            "files": [
                {
                    "path": f.path,
                    "size": f.size,
                    "lfs": f.lfs,
                }
                for f in snapshot.files
            ],
        }

    def _deserialize_snapshot(self, data: Dict[str, Any]) -> RepoSnapshot:
        files = [
            RepoFile(
                path=f.get("path", ""),
                size=f.get("size"),
                lfs=f.get("lfs"),
            )
            for f in (data.get("files") or [])
            if f.get("path")
        ]
        return RepoSnapshot(
            repo_id=data.get("repo_id", ""),
            revision=data.get("revision", "main"),
            sha=data.get("sha"),
            last_modified=data.get("last_modified"),
            pipeline_tag=data.get("pipeline_tag"),
            tags=list(data.get("tags") or []),
            library_name=data.get("library_name"),
            files=files,
        )
