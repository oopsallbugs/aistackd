"""Sync ownership state paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aistackd.state.profiles import ProfileStatePaths

SYNC_DIRECTORY_NAME = "sync"
OWNERSHIP_MANIFEST_FILE_NAME = "ownership_manifest.json"


@dataclass(frozen=True)
class SyncStatePaths:
    """Canonical sync-related state paths."""

    sync_dir: Path
    ownership_manifest_path: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> "SyncStatePaths":
        """Derive sync state paths from a project root."""
        runtime_state_root = ProfileStatePaths.from_project_root(project_root).runtime_state_root
        sync_dir = runtime_state_root / SYNC_DIRECTORY_NAME
        return cls(
            sync_dir=sync_dir,
            ownership_manifest_path=sync_dir / OWNERSHIP_MANIFEST_FILE_NAME,
        )
