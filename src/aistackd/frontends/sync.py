"""Frontend sync contracts, ownership, and write helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from aistackd.frontends.adapters import get_frontend_adapter
from aistackd.frontends.adapters.base import FrontendAdapterPlan
from aistackd.frontends.catalog import normalize_frontend_targets
from aistackd.runtime.config import RuntimeConfig
from aistackd.skills.catalog import BASELINE_SKILLS, BASELINE_TOOLS, load_baseline_skill_contents
from aistackd.state.files import write_json_atomic
from aistackd.state.sync import SyncStatePaths

CURRENT_SYNC_MANIFEST_SCHEMA_VERSION = "v1alpha1"
CURRENT_SYNC_OWNERSHIP_SCHEMA_VERSION = "v1alpha1"


class SyncError(RuntimeError):
    """Raised when sync planning or writing fails."""


@dataclass(frozen=True)
class SyncRequest:
    """A sync request describing target frontends and preview intent."""

    targets: tuple[str, ...]
    dry_run: bool = True

    @classmethod
    def create(
        cls,
        targets: Sequence[str] | None = None,
        dry_run: bool = True,
    ) -> "SyncRequest":
        return cls(targets=normalize_frontend_targets(targets), dry_run=dry_run)


@dataclass(frozen=True)
class SyncManifest:
    """Sync manifest planned from the active runtime config."""

    schema_version: str
    active_profile: str
    mode: str
    dry_run: bool
    targets: tuple[FrontendAdapterPlan, ...]

    @classmethod
    def create(
        cls,
        runtime_config: RuntimeConfig,
        request: SyncRequest,
        baseline_skills: Sequence[str] = BASELINE_SKILLS,
        baseline_tools: Sequence[str] = BASELINE_TOOLS,
    ) -> "SyncManifest":
        """Build a sync manifest for the requested frontends."""
        plans = tuple(
            get_frontend_adapter(frontend).build_plan(
                runtime_config=runtime_config,
                baseline_skills=baseline_skills,
                baseline_tools=baseline_tools,
            )
            for frontend in request.targets
        )
        return cls(
            schema_version=CURRENT_SYNC_MANIFEST_SCHEMA_VERSION,
            active_profile=runtime_config.active_profile,
            mode=runtime_config.mode,
            dry_run=request.dry_run,
            targets=plans,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "schema_version": self.schema_version,
            "active_profile": self.active_profile,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "targets": [target.to_dict() for target in self.targets],
        }


@dataclass(frozen=True)
class SyncOwnershipTarget:
    """Tracked managed ownership for one synced frontend."""

    frontend: str
    activation_mode: str
    managed_paths: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "frontend": self.frontend,
            "activation_mode": self.activation_mode,
            "managed_paths": list(self.managed_paths),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SyncOwnershipManifest:
    """Repo-owned ownership manifest for managed sync outputs."""

    schema_version: str
    active_profile: str
    mode: str
    targets: tuple[SyncOwnershipTarget, ...]

    @classmethod
    def from_manifest(cls, manifest: SyncManifest) -> "SyncOwnershipManifest":
        """Build ownership state from a sync manifest."""
        return cls(
            schema_version=CURRENT_SYNC_OWNERSHIP_SCHEMA_VERSION,
            active_profile=manifest.active_profile,
            mode=manifest.mode,
            targets=tuple(
                SyncOwnershipTarget(
                    frontend=target.frontend,
                    activation_mode=target.activation_mode,
                    managed_paths=tuple(managed_path.path for managed_path in target.managed_paths),
                    notes=target.notes,
                )
                for target in manifest.targets
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "schema_version": self.schema_version,
            "active_profile": self.active_profile,
            "mode": self.mode,
            "targets": [target.to_dict() for target in self.targets],
        }


@dataclass(frozen=True)
class SyncWriteResult:
    """Result of applying a sync manifest to disk."""

    manifest: SyncManifest
    ownership_manifest_path: str
    written_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "manifest": self.manifest.to_dict(),
            "ownership_manifest_path": self.ownership_manifest_path,
            "written_paths": list(self.written_paths),
        }


def apply_sync_manifest(project_root: Path, manifest: SyncManifest) -> SyncWriteResult:
    """Write managed sync content and persist the ownership manifest."""
    root = project_root.resolve()
    try:
        skill_names = sorted(
            {skill_name for target in manifest.targets for skill_name in target.baseline_skills}
        )
        skill_contents = load_baseline_skill_contents(skill_names)
        tool_contents: dict[str, str] = {}

        written_paths: list[str] = []
        for target in manifest.targets:
            adapter = get_frontend_adapter(target.frontend)
            written_paths.extend(adapter.apply(root, target, skill_contents, tool_contents))

        ownership_manifest = SyncOwnershipManifest.from_manifest(manifest)
        ownership_path = SyncStatePaths.from_project_root(root).ownership_manifest_path
        write_json_atomic(ownership_path, ownership_manifest.to_dict())
        written_paths.append(str(ownership_path))
    except (FileNotFoundError, ValueError) as exc:
        raise SyncError(str(exc)) from exc

    return SyncWriteResult(
        manifest=manifest,
        ownership_manifest_path=str(ownership_path),
        written_paths=tuple(written_paths),
    )
