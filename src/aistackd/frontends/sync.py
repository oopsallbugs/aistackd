"""Frontend sync contracts, ownership, and write helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from aistackd.frontends.adapters import get_frontend_adapter
from aistackd.frontends.adapters.base import FrontendAdapterPlan, ManagedPath
from aistackd.frontends.catalog import normalize_frontend_targets
from aistackd.runtime.config import RuntimeConfig
from aistackd.skills.catalog import (
    BASELINE_SKILLS,
    BASELINE_TOOLS,
    load_baseline_skill_contents,
    load_baseline_tool_contents,
)
from aistackd.state.files import load_json_object, write_json_atomic
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
    managed_paths: tuple[ManagedPath, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "frontend": self.frontend,
            "activation_mode": self.activation_mode,
            "managed_paths": [managed_path.to_dict() for managed_path in self.managed_paths],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SyncOwnershipTarget":
        """Decode a tracked frontend ownership target."""
        frontend = payload.get("frontend")
        activation_mode = payload.get("activation_mode")
        managed_paths = payload.get("managed_paths")
        notes = payload.get("notes", ())

        if not isinstance(frontend, str) or not isinstance(activation_mode, str):
            raise ValueError("ownership targets require string 'frontend' and 'activation_mode'")
        if not isinstance(managed_paths, list):
            raise ValueError("ownership targets require list 'managed_paths'")
        if not isinstance(notes, list):
            raise ValueError("ownership targets require list 'notes'")
        if not all(isinstance(entry, dict) for entry in managed_paths):
            raise ValueError("managed path entries must be objects")

        return cls(
            frontend=frontend,
            activation_mode=activation_mode,
            managed_paths=tuple(ManagedPath.from_dict(entry) for entry in managed_paths),
            notes=tuple(str(note) for note in notes),
        )


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
                    managed_paths=target.managed_paths,
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

    @classmethod
    def load(cls, project_root: Path) -> "SyncOwnershipManifest | None":
        """Load an existing ownership manifest from disk, if present."""
        ownership_path = SyncStatePaths.from_project_root(project_root).ownership_manifest_path
        if not ownership_path.exists():
            return None
        payload = load_json_object(ownership_path)
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SyncOwnershipManifest":
        """Decode an ownership manifest from disk."""
        schema_version = payload.get("schema_version")
        active_profile = payload.get("active_profile")
        mode = payload.get("mode")
        targets = payload.get("targets")

        if not isinstance(schema_version, str):
            raise ValueError("ownership manifest requires string 'schema_version'")
        if not isinstance(active_profile, str):
            raise ValueError("ownership manifest requires string 'active_profile'")
        if not isinstance(mode, str):
            raise ValueError("ownership manifest requires string 'mode'")
        if not isinstance(targets, list):
            raise ValueError("ownership manifest requires list 'targets'")
        if not all(isinstance(entry, dict) for entry in targets):
            raise ValueError("ownership manifest targets must be objects")

        return cls(
            schema_version=schema_version,
            active_profile=active_profile,
            mode=mode,
            targets=tuple(SyncOwnershipTarget.from_dict(entry) for entry in targets),
        )

    def target_by_frontend(self, frontend: str) -> SyncOwnershipTarget | None:
        """Return the ownership target for a frontend, if present."""
        for target in self.targets:
            if target.frontend == frontend:
                return target
        return None


@dataclass(frozen=True)
class SyncChange:
    """A single planned sync change."""

    action: str
    frontend: str
    managed_path: ManagedPath

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""
        return {
            "action": self.action,
            "frontend": self.frontend,
            "kind": self.managed_path.kind,
            "path": self.managed_path.path,
        }


@dataclass(frozen=True)
class SyncWriteResult:
    """Result of applying a sync manifest to disk."""

    manifest: SyncManifest
    ownership_manifest_path: str
    written_paths: tuple[str, ...]
    removed_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "manifest": self.manifest.to_dict(),
            "ownership_manifest_path": self.ownership_manifest_path,
            "written_paths": list(self.written_paths),
            "removed_paths": list(self.removed_paths),
        }


def evaluate_sync_manifest(project_root: Path, manifest: SyncManifest) -> tuple[SyncChange, ...]:
    """Compare a sync manifest to current ownership state."""
    root = project_root.resolve()
    current_ownership = SyncOwnershipManifest.load(root)
    current_entries = set()
    if current_ownership is not None:
        for target in current_ownership.targets:
            for managed_path in target.managed_paths:
                current_entries.add((target.frontend, managed_path.kind, managed_path.path))

    changes: list[SyncChange] = []
    desired_entries = set()

    for target in manifest.targets:
        for managed_path in target.managed_paths:
            entry_key = (target.frontend, managed_path.kind, managed_path.path)
            desired_entries.add(entry_key)
            if entry_key in current_entries:
                action = "update" if managed_path.kind == "provider_config" else "keep"
            else:
                action = "create"
            changes.append(SyncChange(action=action, frontend=target.frontend, managed_path=managed_path))

    if current_ownership is not None:
        for target in current_ownership.targets:
            for managed_path in target.managed_paths:
                entry_key = (target.frontend, managed_path.kind, managed_path.path)
                if entry_key not in desired_entries:
                    changes.append(
                        SyncChange(action="remove", frontend=target.frontend, managed_path=managed_path)
                    )

    return tuple(changes)


def apply_sync_manifest(project_root: Path, manifest: SyncManifest) -> SyncWriteResult:
    """Write managed sync content and persist the ownership manifest."""
    root = project_root.resolve()
    try:
        current_ownership = SyncOwnershipManifest.load(root)
        skill_names = sorted(
            {skill_name for target in manifest.targets for skill_name in target.baseline_skills}
        )
        tool_names = sorted(
            {tool_name for target in manifest.targets for tool_name in target.baseline_tools}
        )
        skill_contents = load_baseline_skill_contents(skill_names)
        tool_contents = load_baseline_tool_contents(
            tool_names,
            base_url=_derive_tool_base_url(manifest),
            responses_base_url=_derive_tool_responses_base_url(manifest),
            api_key_env=_derive_tool_api_key_env(manifest),
        )

        removed_paths = _prune_stale_managed_paths(root, manifest, current_ownership)
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
        removed_paths=tuple(removed_paths),
    )


def _prune_stale_managed_paths(
    project_root: Path,
    manifest: SyncManifest,
    current_ownership: SyncOwnershipManifest | None,
) -> list[str]:
    """Remove managed paths that are no longer part of the desired manifest."""
    if current_ownership is None:
        return []

    desired_entries = {
        (target.frontend, managed_path.kind, managed_path.path)
        for target in manifest.targets
        for managed_path in target.managed_paths
    }
    stale_by_frontend: dict[str, list[ManagedPath]] = {}

    for target in current_ownership.targets:
        for managed_path in target.managed_paths:
            entry_key = (target.frontend, managed_path.kind, managed_path.path)
            if entry_key not in desired_entries:
                stale_by_frontend.setdefault(target.frontend, []).append(managed_path)

    removed_paths: list[str] = []
    for frontend, managed_paths in stale_by_frontend.items():
        adapter = get_frontend_adapter(frontend)
        removed_paths.extend(adapter.cleanup(project_root, tuple(managed_paths)))

    return removed_paths


def _derive_tool_base_url(manifest: SyncManifest) -> str:
    responses_base_url = _derive_tool_responses_base_url(manifest)
    if responses_base_url.endswith("/v1"):
        return responses_base_url[: -len("/v1")]
    return responses_base_url


def _derive_tool_responses_base_url(manifest: SyncManifest) -> str:
    if not manifest.targets:
        raise SyncError("cannot render baseline tools without at least one frontend target")
    return manifest.targets[0].provider_base_url


def _derive_tool_api_key_env(manifest: SyncManifest) -> str:
    if not manifest.targets:
        raise SyncError("cannot render baseline tools without at least one frontend target")
    return manifest.targets[0].api_key_env
