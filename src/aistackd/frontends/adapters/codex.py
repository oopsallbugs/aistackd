"""Codex frontend adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from aistackd.frontends.adapters.base import FrontendAdapterPlan, ManagedPath
from aistackd.runtime.config import RuntimeConfig
from aistackd.state.files import (
    delete_file_if_exists,
    load_toml_object,
    prune_empty_directories,
    write_toml_atomic,
    write_text_atomic,
)

CODEX_PROVIDER_CONFIG_PATH = Path(".codex") / "config.toml"
CODEX_SKILLS_ROOT = Path(".codex") / "skills"
CODEX_PROFILE_NAME = "aistackd"
CODEX_PROVIDER_ID = "aistackd"
CODEX_DEFAULT_MODEL = "default"
CODEX_WIRE_API = "responses"


class CodexAdapter:
    """Adapter that writes project-local Codex config."""

    name = "codex"

    def build_plan(
        self,
        runtime_config: RuntimeConfig,
        baseline_skills: Sequence[str],
        baseline_tools: Sequence[str],
    ) -> FrontendAdapterPlan:
        skill_paths = tuple(
            ManagedPath("skill", str(CODEX_SKILLS_ROOT / skill_name / "SKILL.md"))
            for skill_name in baseline_skills
        )
        managed_paths = (ManagedPath("provider_config", str(CODEX_PROVIDER_CONFIG_PATH)),) + skill_paths
        provider_payload = {
            "profile": CODEX_PROFILE_NAME,
            "profiles": {
                CODEX_PROFILE_NAME: {
                    "model_provider": CODEX_PROVIDER_ID,
                    "model": CODEX_DEFAULT_MODEL,
                }
            },
            "model_providers": {
                CODEX_PROVIDER_ID: {
                    "name": CODEX_PROVIDER_ID,
                    "base_url": runtime_config.responses_base_url,
                    "env_key": runtime_config.api_key_env,
                    "wire_api": CODEX_WIRE_API,
                }
            },
        }
        return FrontendAdapterPlan(
            frontend=self.name,
            provider_kind="openai_compatible",
            provider_name=CODEX_PROVIDER_ID,
            provider_base_url=runtime_config.responses_base_url,
            api_key_env=runtime_config.api_key_env,
            provider_config_path=str(CODEX_PROVIDER_CONFIG_PATH),
            provider_payload=provider_payload,
            managed_paths=managed_paths,
            baseline_skills=tuple(baseline_skills),
            baseline_tools=tuple(baseline_tools),
            activation_mode="project_local",
            notes=(
                "provider settings are merged into project-local .codex/config.toml while preserving unrelated keys",
            ),
        )

    def apply(
        self,
        project_root: Path,
        plan: FrontendAdapterPlan,
        skill_contents: Mapping[str, str],
        tool_contents: Mapping[str, str],
    ) -> tuple[str, ...]:
        written_paths: list[str] = []

        provider_config_path = project_root / plan.provider_config_path
        existing_payload = load_toml_object(provider_config_path)
        merged_payload = self._merge_provider_payload(existing_payload, plan.provider_payload)
        write_toml_atomic(provider_config_path, merged_payload)
        written_paths.append(str(provider_config_path))

        for managed_path in plan.managed_paths:
            if managed_path.kind != "skill":
                continue
            skill_name = Path(managed_path.path).parts[-2]
            target_path = project_root / managed_path.path
            write_text_atomic(target_path, skill_contents[skill_name])
            written_paths.append(str(target_path))

        return tuple(written_paths)

    def cleanup(
        self,
        project_root: Path,
        managed_paths: Sequence[ManagedPath],
    ) -> tuple[str, ...]:
        """Remove stale Codex managed content while preserving unrelated config."""
        changed_paths: list[str] = []
        root = project_root.resolve()

        for managed_path in managed_paths:
            target_path = root / managed_path.path
            if managed_path.kind == "provider_config" and target_path.name == CODEX_PROVIDER_CONFIG_PATH.name:
                changed_paths.extend(self._cleanup_provider_config(target_path, root))
                continue

            if delete_file_if_exists(target_path):
                changed_paths.append(str(target_path))
            changed_paths.extend(prune_empty_directories(target_path.parent, root))

        return tuple(changed_paths)

    @staticmethod
    def _merge_provider_payload(
        existing_payload: dict[str, object],
        provider_payload: dict[str, object],
    ) -> dict[str, object]:
        """Merge managed Codex profile keys while preserving unrelated config."""
        merged_payload = dict(existing_payload)
        merged_payload["profile"] = provider_payload["profile"]

        existing_profiles = existing_payload.get("profiles")
        profile_block = dict(existing_profiles) if isinstance(existing_profiles, dict) else {}
        managed_profiles = provider_payload["profiles"]
        if isinstance(managed_profiles, dict):
            profile_block.update(managed_profiles)
        merged_payload["profiles"] = profile_block

        existing_model_providers = existing_payload.get("model_providers")
        provider_block = (
            dict(existing_model_providers) if isinstance(existing_model_providers, dict) else {}
        )
        managed_model_providers = provider_payload["model_providers"]
        if isinstance(managed_model_providers, dict):
            provider_block.update(managed_model_providers)
        merged_payload["model_providers"] = provider_block

        return merged_payload

    def _cleanup_provider_config(self, target_path: Path, project_root: Path) -> tuple[str, ...]:
        """Remove repo-managed Codex provider state from an existing config file."""
        if not target_path.exists():
            return ()

        existing_payload = load_toml_object(target_path)
        cleaned_payload = self._remove_managed_provider_payload(existing_payload)
        changed_paths: list[str] = []

        if not cleaned_payload:
            if delete_file_if_exists(target_path):
                changed_paths.append(str(target_path))
        else:
            write_toml_atomic(target_path, cleaned_payload)
            changed_paths.append(str(target_path))

        changed_paths.extend(prune_empty_directories(target_path.parent, project_root))
        return tuple(changed_paths)

    @staticmethod
    def _remove_managed_provider_payload(existing_payload: dict[str, object]) -> dict[str, object]:
        """Remove repo-managed Codex profile and provider state while preserving unrelated keys."""
        cleaned_payload = dict(existing_payload)

        if cleaned_payload.get("profile") == CODEX_PROFILE_NAME:
            cleaned_payload.pop("profile", None)

        existing_profiles = cleaned_payload.get("profiles")
        if isinstance(existing_profiles, dict):
            profile_block = dict(existing_profiles)
            profile_block.pop(CODEX_PROFILE_NAME, None)
            if profile_block:
                cleaned_payload["profiles"] = profile_block
            else:
                cleaned_payload.pop("profiles", None)

        existing_model_providers = cleaned_payload.get("model_providers")
        if isinstance(existing_model_providers, dict):
            provider_block = dict(existing_model_providers)
            provider_block.pop(CODEX_PROVIDER_ID, None)
            if provider_block:
                cleaned_payload["model_providers"] = provider_block
            else:
                cleaned_payload.pop("model_providers", None)

        return cleaned_payload
