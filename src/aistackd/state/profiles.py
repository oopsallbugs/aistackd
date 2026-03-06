"""Profile state paths for the scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RUNTIME_STATE_DIRECTORY_NAME = ".aistackd"
PROFILES_DIRECTORY_NAME = "profiles"
ACTIVE_PROFILE_FILE_NAME = "active_profile"


@dataclass(frozen=True)
class ProfileStatePaths:
    """Canonical profile-related state paths."""

    runtime_state_root: Path
    profiles_dir: Path
    active_profile_path: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> "ProfileStatePaths":
        """Derive profile state paths from a project root."""
        root = project_root.resolve()
        runtime_state_root = root / RUNTIME_STATE_DIRECTORY_NAME
        return cls(
            runtime_state_root=runtime_state_root,
            profiles_dir=runtime_state_root / PROFILES_DIRECTORY_NAME,
            active_profile_path=runtime_state_root / ACTIVE_PROFILE_FILE_NAME,
        )
