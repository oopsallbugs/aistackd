"""Codex frontend adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from aistackd.frontends.adapters.base import FrontendAdapterPlan, ManagedPath
from aistackd.runtime.config import RuntimeConfig
from aistackd.state.files import load_json_object, write_json_atomic, write_text_atomic

CODEX_PROVIDER_CONFIG_PATH = Path(".codex") / "aistackd.json"
CODEX_SKILLS_ROOT = Path(".codex") / "skills"


class CodexAdapter:
    """Adapter that writes repo-owned Codex sync state."""

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
            "schema_version": "v1alpha1",
            "active_profile": runtime_config.active_profile,
            "mode": runtime_config.mode,
            "provider": {
                "kind": "openai_compatible",
                "name": "aistackd",
                "base_url": runtime_config.responses_base_url,
                "api_key_env": runtime_config.api_key_env,
            },
        }
        return FrontendAdapterPlan(
            frontend=self.name,
            provider_kind="openai_compatible",
            provider_name="aistackd",
            provider_base_url=runtime_config.responses_base_url,
            api_key_env=runtime_config.api_key_env,
            provider_config_path=str(CODEX_PROVIDER_CONFIG_PATH),
            provider_payload=provider_payload,
            managed_paths=managed_paths,
            baseline_skills=tuple(baseline_skills),
            baseline_tools=tuple(baseline_tools),
            activation_mode="staged",
            notes=(
                "provider settings are written to a repo-owned Codex adapter file; direct Codex provider wiring is not implemented yet",
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
        existing_payload = load_json_object(provider_config_path)
        merged_payload = dict(existing_payload)
        merged_payload.update(plan.provider_payload)
        write_json_atomic(provider_config_path, merged_payload)
        written_paths.append(str(provider_config_path))

        for managed_path in plan.managed_paths:
            if managed_path.kind != "skill":
                continue
            skill_name = Path(managed_path.path).parts[-2]
            target_path = project_root / managed_path.path
            write_text_atomic(target_path, skill_contents[skill_name])
            written_paths.append(str(target_path))

        return tuple(written_paths)
