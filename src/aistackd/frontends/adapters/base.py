"""Common frontend adapter contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aistackd.runtime.config import RuntimeConfig


@dataclass(frozen=True)
class ManagedPath:
    """A repo-managed path produced by a frontend adapter."""

    kind: str
    path: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""
        return {"kind": self.kind, "path": self.path}

    @classmethod
    def from_object(cls, payload: object) -> "ManagedPath":
        """Decode a managed path from current or legacy manifest content."""
        if isinstance(payload, str):
            return cls(kind=_infer_managed_path_kind(payload), path=payload)
        if not isinstance(payload, dict):
            raise ValueError("managed path entries must be strings or objects")

        kind = payload.get("kind")
        path = payload.get("path")
        if not isinstance(kind, str) or not isinstance(path, str):
            raise ValueError("managed path entries require string 'kind' and 'path' fields")
        return cls(kind=kind, path=path)


@dataclass(frozen=True)
class FrontendAdapterPlan:
    """Per-frontend sync plan with concrete managed paths."""

    frontend: str
    provider_kind: str
    provider_name: str
    provider_base_url: str
    api_key_env: str
    provider_config_path: str
    provider_payload: dict[str, object]
    managed_paths: tuple[ManagedPath, ...]
    baseline_skills: tuple[str, ...]
    baseline_tools: tuple[str, ...]
    activation_mode: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "frontend": self.frontend,
            "provider_kind": self.provider_kind,
            "provider_name": self.provider_name,
            "provider_base_url": self.provider_base_url,
            "api_key_env": self.api_key_env,
            "provider_config_path": self.provider_config_path,
            "provider_payload": self.provider_payload,
            "managed_paths": [path.to_dict() for path in self.managed_paths],
            "baseline_skills": list(self.baseline_skills),
            "baseline_tools": list(self.baseline_tools),
            "activation_mode": self.activation_mode,
            "notes": list(self.notes),
        }


class FrontendAdapter(Protocol):
    """Protocol implemented by all frontend adapters."""

    name: str

    def build_plan(
        self,
        runtime_config: RuntimeConfig,
        baseline_skills: Sequence[str],
        baseline_tools: Sequence[str],
    ) -> FrontendAdapterPlan:
        """Build a concrete plan for one frontend."""

    def apply(
        self,
        project_root: Path,
        plan: FrontendAdapterPlan,
        skill_contents: Mapping[str, str],
        tool_contents: Mapping[str, str],
    ) -> tuple[str, ...]:
        """Write managed content for one frontend and return written paths."""

    def cleanup(
        self,
        project_root: Path,
        managed_paths: Sequence[ManagedPath],
    ) -> tuple[str, ...]:
        """Remove stale managed content for one frontend and return changed paths."""


def _infer_managed_path_kind(path: str) -> str:
    """Infer a managed path kind from a legacy path-only manifest entry."""
    if path.endswith("/SKILL.md"):
        return "skill"
    if path.endswith(".json") or path.endswith(".toml"):
        return "provider_config"
    return "file"
