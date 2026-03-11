"""Runtime config contracts derived from stored profiles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aistackd.frontends.catalog import normalize_frontend_targets
from aistackd.models.selection import frontend_model_key
from aistackd.runtime.host import DEFAULT_BACKEND_CONTEXT_SIZE, DEFAULT_BACKEND_PREDICT_LIMIT
from aistackd.runtime.modes import RuntimeMode
from aistackd.state.profiles import Profile

CURRENT_RUNTIME_CONFIG_SCHEMA_VERSION = "v1alpha2"


@dataclass(frozen=True)
class RuntimeConfig:
    """Minimal runtime config derived from an active profile."""

    schema_version: str
    mode: str
    active_profile: str
    base_url: str
    responses_base_url: str
    api_key_env: str
    model: str
    frontend_model_key: str
    frontend_context_limit: int
    frontend_output_limit: int
    profile_role_hint: str | None = None
    frontend_targets: tuple[str, ...] = ()

    @classmethod
    def for_client(
        cls,
        profile: Profile,
        frontend_targets: Sequence[str] | None = None,
    ) -> "RuntimeConfig":
        """Build a client-mode runtime config from a stored profile."""
        normalized_profile = profile.normalized()
        normalized_frontends = normalize_frontend_targets(frontend_targets)
        base_url = normalized_profile.base_url
        model = normalized_profile.model
        return cls(
            schema_version=CURRENT_RUNTIME_CONFIG_SCHEMA_VERSION,
            mode=RuntimeMode.CLIENT.value,
            active_profile=normalized_profile.name,
            base_url=base_url,
            responses_base_url=f"{base_url.rstrip('/')}/v1",
            api_key_env=normalized_profile.api_key_env,
            model=model,
            frontend_model_key=frontend_model_key(model),
            frontend_context_limit=DEFAULT_BACKEND_CONTEXT_SIZE,
            frontend_output_limit=min(DEFAULT_BACKEND_PREDICT_LIMIT, DEFAULT_BACKEND_CONTEXT_SIZE),
            profile_role_hint=normalized_profile.role_hint,
            frontend_targets=normalized_frontends,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "active_profile": self.active_profile,
            "base_url": self.base_url,
            "responses_base_url": self.responses_base_url,
            "api_key_env": self.api_key_env,
            "model": self.model,
            "frontend_model_key": self.frontend_model_key,
            "frontend_context_limit": self.frontend_context_limit,
            "frontend_output_limit": self.frontend_output_limit,
            "frontend_targets": list(self.frontend_targets),
        }
        if self.profile_role_hint is not None:
            payload["profile_role_hint"] = self.profile_role_hint
        return payload
