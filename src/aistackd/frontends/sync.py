"""Frontend sync contracts and planning helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aistackd.frontends.catalog import normalize_frontend_targets
from aistackd.runtime.config import RuntimeConfig
from aistackd.skills.catalog import PLANNED_BASELINE_SKILLS, PLANNED_BASELINE_TOOLS

CURRENT_SYNC_MANIFEST_SCHEMA_VERSION = "v1alpha1"
SYNC_PROVIDER_KIND = "openai_compatible"
SYNC_PROVIDER_NAME = "aistackd"


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
class SyncTargetPlan:
    """Per-frontend sync plan derived from runtime config."""

    frontend: str
    provider_kind: str
    provider_name: str
    provider_base_url: str
    api_key_env: str
    baseline_skills: tuple[str, ...]
    baseline_tools: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "frontend": self.frontend,
            "provider_kind": self.provider_kind,
            "provider_name": self.provider_name,
            "provider_base_url": self.provider_base_url,
            "api_key_env": self.api_key_env,
            "baseline_skills": list(self.baseline_skills),
            "baseline_tools": list(self.baseline_tools),
        }


@dataclass(frozen=True)
class SyncManifest:
    """Sync manifest planned from the active runtime config."""

    schema_version: str
    active_profile: str
    mode: str
    dry_run: bool
    targets: tuple[SyncTargetPlan, ...]

    @classmethod
    def create(
        cls,
        runtime_config: RuntimeConfig,
        request: SyncRequest,
        baseline_skills: Sequence[str] = PLANNED_BASELINE_SKILLS,
        baseline_tools: Sequence[str] = PLANNED_BASELINE_TOOLS,
    ) -> "SyncManifest":
        """Build a sync manifest for the requested frontends."""
        plans = tuple(
            SyncTargetPlan(
                frontend=frontend,
                provider_kind=SYNC_PROVIDER_KIND,
                provider_name=SYNC_PROVIDER_NAME,
                provider_base_url=runtime_config.responses_base_url,
                api_key_env=runtime_config.api_key_env,
                baseline_skills=tuple(baseline_skills),
                baseline_tools=tuple(baseline_tools),
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
            "targets": [plan.to_dict() for plan in self.targets],
        }
