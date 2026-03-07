"""OpenCode frontend adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from aistackd.frontends.adapters.base import FrontendAdapterPlan, ManagedPath
from aistackd.runtime.config import RuntimeConfig
from aistackd.state.files import load_json_object, write_json_atomic, write_text_atomic

OPENCODE_SCHEMA_URL = "https://opencode.ai/config.json"
OPENCODE_PROVIDER_KEY = "aistackd"
OPENCODE_PROVIDER_NPM = "@ai-sdk/openai-compatible"
OPENCODE_PROVIDER_CONFIG_PATH = Path("opencode.json")
OPENCODE_SKILLS_ROOT = Path(".opencode") / "skills"
OPENCODE_DEFAULT_MODEL = "default"


class OpenCodeAdapter:
    """Adapter that writes project-local OpenCode config."""

    name = "opencode"

    def build_plan(
        self,
        runtime_config: RuntimeConfig,
        baseline_skills: Sequence[str],
        baseline_tools: Sequence[str],
    ) -> FrontendAdapterPlan:
        skill_paths = tuple(
            ManagedPath("skill", str(OPENCODE_SKILLS_ROOT / skill_name / "SKILL.md"))
            for skill_name in baseline_skills
        )
        managed_paths = (ManagedPath("provider_config", str(OPENCODE_PROVIDER_CONFIG_PATH)),) + skill_paths
        provider_payload = {
            "$schema": OPENCODE_SCHEMA_URL,
            "provider": {
                OPENCODE_PROVIDER_KEY: {
                    "npm": OPENCODE_PROVIDER_NPM,
                    "name": "aistackd",
                    "options": {"baseURL": runtime_config.responses_base_url},
                    "models": {
                        OPENCODE_DEFAULT_MODEL: {
                            "name": OPENCODE_DEFAULT_MODEL,
                            "tools": True,
                            "limit": {"context": 32768, "output": 8192},
                        }
                    },
                }
            },
            "model": f"{OPENCODE_PROVIDER_KEY}/{OPENCODE_DEFAULT_MODEL}",
        }
        return FrontendAdapterPlan(
            frontend=self.name,
            provider_kind="openai_compatible",
            provider_name="aistackd",
            provider_base_url=runtime_config.responses_base_url,
            api_key_env=runtime_config.api_key_env,
            provider_config_path=str(OPENCODE_PROVIDER_CONFIG_PATH),
            provider_payload=provider_payload,
            managed_paths=managed_paths,
            baseline_skills=tuple(baseline_skills),
            baseline_tools=tuple(baseline_tools),
            activation_mode="project_local",
            notes=(
                "provider settings are merged into project-local opencode.json while preserving unrelated keys",
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
        merged_payload = self._merge_provider_payload(existing_payload, plan.provider_payload)
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

    @staticmethod
    def _merge_provider_payload(
        existing_payload: dict[str, object],
        provider_payload: dict[str, object],
    ) -> dict[str, object]:
        """Merge managed OpenCode provider keys while preserving unrelated config."""
        merged_payload = dict(existing_payload)
        merged_payload.setdefault("$schema", provider_payload["$schema"])
        existing_provider = existing_payload.get("provider")
        provider_block = dict(existing_provider) if isinstance(existing_provider, dict) else {}
        managed_provider = provider_payload["provider"]
        if isinstance(managed_provider, dict):
            provider_block.update(managed_provider)
        merged_payload["provider"] = provider_block
        merged_payload["model"] = provider_payload["model"]
        return merged_payload
