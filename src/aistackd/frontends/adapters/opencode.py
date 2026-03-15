"""OpenCode frontend adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from aistackd.frontends.adapters.base import FrontendAdapterPlan, ManagedPath
from aistackd.frontends.guidance import build_frontend_guidance
from aistackd.runtime.config import RuntimeConfig
from aistackd.skills.project_local import project_local_skill_note
from aistackd.state.files import (
    delete_file_if_exists,
    load_json_object,
    prune_empty_directories,
    write_executable_text_atomic,
    write_json_atomic,
    write_text_atomic,
)

OPENCODE_SCHEMA_URL = "https://opencode.ai/config.json"
OPENCODE_PROVIDER_KEY = "aistackd"
OPENCODE_PROVIDER_NPM = "@ai-sdk/openai-compatible"
OPENCODE_PROVIDER_CONFIG_PATH = Path("opencode.json")
OPENCODE_SKILLS_ROOT = Path(".opencode") / "skills"
OPENCODE_TOOLS_ROOT = Path(".opencode") / "tools"


class OpenCodeAdapter:
    """Adapter that writes project-local OpenCode config."""

    name = "opencode"

    def build_plan(
        self,
        runtime_config: RuntimeConfig,
        baseline_skills: Sequence[str],
        baseline_tools: Sequence[str],
    ) -> FrontendAdapterPlan:
        guidance = build_frontend_guidance(self.name, runtime_config.api_key_env)
        skill_paths = tuple(
            ManagedPath("skill", str(OPENCODE_SKILLS_ROOT / skill_name / "SKILL.md"))
            for skill_name in baseline_skills
        )
        tool_paths = tuple(
            ManagedPath("tool", str(OPENCODE_TOOLS_ROOT / f"{tool_name}.py"))
            for tool_name in baseline_tools
        )
        managed_paths = (ManagedPath("provider_config", str(OPENCODE_PROVIDER_CONFIG_PATH)),) + skill_paths + tool_paths
        provider_payload = {
            "$schema": OPENCODE_SCHEMA_URL,
            "provider": {
                OPENCODE_PROVIDER_KEY: {
                    "npm": OPENCODE_PROVIDER_NPM,
                    "name": "aistackd",
                    "options": {
                        "baseURL": runtime_config.responses_base_url,
                        "apiKey": f"{{env:{runtime_config.api_key_env}}}",
                    },
                    "models": {
                        runtime_config.frontend_model_key: {
                            "name": runtime_config.model,
                            "tools": True,
                            "limit": {
                                "context": runtime_config.frontend_context_limit,
                                "output": runtime_config.frontend_output_limit,
                            },
                        }
                    },
                }
            },
            "model": f"{OPENCODE_PROVIDER_KEY}/{runtime_config.frontend_model_key}",
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
                f"synced operator tools default to profile '{runtime_config.active_profile}' at {runtime_config.base_url}",
                "recommended first-run check: aistackd doctor ready --frontend opencode",
                f"launch command: {guidance.launch_command}",
                guidance.api_key_hint,
                project_local_skill_note(self.name),
                "tool-calling examples stay client-managed; the host transports function calls but does not execute repo tools",
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
                if managed_path.kind != "tool":
                    continue
                tool_name = Path(managed_path.path).stem
                target_path = project_root / managed_path.path
                write_executable_text_atomic(target_path, tool_contents[tool_name])
                written_paths.append(str(target_path))
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
        """Remove stale managed OpenCode content while preserving unrelated config."""
        changed_paths: list[str] = []
        root = project_root.resolve()

        for managed_path in managed_paths:
            target_path = root / managed_path.path
            if managed_path.kind == "provider_config":
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

    def _cleanup_provider_config(self, target_path: Path, project_root: Path) -> tuple[str, ...]:
        """Remove managed OpenCode provider keys from an existing config file."""
        if not target_path.exists():
            return ()

        existing_payload = load_json_object(target_path)
        cleaned_payload = self._remove_managed_provider_payload(existing_payload)
        changed_paths: list[str] = []

        if self._can_delete_provider_config(cleaned_payload):
            if delete_file_if_exists(target_path):
                changed_paths.append(str(target_path))
        else:
            write_json_atomic(target_path, cleaned_payload)
            changed_paths.append(str(target_path))

        changed_paths.extend(prune_empty_directories(target_path.parent, project_root))
        return tuple(changed_paths)

    @staticmethod
    def _remove_managed_provider_payload(existing_payload: dict[str, object]) -> dict[str, object]:
        """Remove repo-managed OpenCode provider state while preserving unrelated keys."""
        cleaned_payload = dict(existing_payload)
        existing_provider = cleaned_payload.get("provider")
        if isinstance(existing_provider, dict):
            provider_block = dict(existing_provider)
            provider_block.pop(OPENCODE_PROVIDER_KEY, None)
            if provider_block:
                cleaned_payload["provider"] = provider_block
            else:
                cleaned_payload.pop("provider", None)

        model_value = cleaned_payload.get("model")
        if isinstance(model_value, str) and model_value.startswith(f"{OPENCODE_PROVIDER_KEY}/"):
            cleaned_payload.pop("model", None)

        return cleaned_payload

    @staticmethod
    def _can_delete_provider_config(payload: dict[str, object]) -> bool:
        """Return ``True`` when no useful unmanaged content remains."""
        remaining_keys = set(payload)
        if not remaining_keys:
            return True
        return remaining_keys == {"$schema"}
