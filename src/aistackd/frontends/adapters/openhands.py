"""OpenHands frontend adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from aistackd.frontends.adapters.base import FrontendAdapterPlan, ManagedPath
from aistackd.runtime.config import RuntimeConfig
from aistackd.skills.project_local import project_local_skill_note
from aistackd.state.files import (
    delete_file_if_exists,
    prune_empty_directories,
    write_text_atomic,
    write_toml_atomic,
)

OPENHANDS_PROVIDER_CONFIG_PATH = Path(".openhands") / "config.toml"
OPENHANDS_MICROAGENTS_ROOT = Path(".openhands") / "microagents"


class OpenHandsAdapter:
    """Adapter that writes conservative project-local OpenHands state."""

    name = "openhands"

    def build_plan(
        self,
        runtime_config: RuntimeConfig,
        baseline_skills: Sequence[str],
        baseline_tools: Sequence[str],
    ) -> FrontendAdapterPlan:
        skill_paths = tuple(
            ManagedPath("skill", str(OPENHANDS_MICROAGENTS_ROOT / f"{skill_name}.md"))
            for skill_name in baseline_skills
        )
        managed_paths = (ManagedPath("provider_config", str(OPENHANDS_PROVIDER_CONFIG_PATH)),) + skill_paths
        provider_payload = {
            "llm": {
                "model": f"openai/{runtime_config.model}",
                "base_url": runtime_config.responses_base_url,
            },
            "agent": {
                "enable_prompt_extensions": True,
            },
        }
        return FrontendAdapterPlan(
            frontend=self.name,
            provider_kind="openai_compatible",
            provider_name="aistackd",
            provider_base_url=runtime_config.responses_base_url,
            api_key_env=runtime_config.api_key_env,
            provider_config_path=str(OPENHANDS_PROVIDER_CONFIG_PATH),
            provider_payload=provider_payload,
            managed_paths=managed_paths,
            baseline_skills=tuple(baseline_skills),
            baseline_tools=(),
            activation_mode="project_local",
            notes=(
                "project-local .openhands/config.toml is written for OpenHands CLI/headless/dev mode; launch with 'openhands --config-file .openhands/config.toml'",
                f"export LLM_API_KEY from {runtime_config.api_key_env} before launching OpenHands, or mirror the same values in the OpenHands settings UI",
                "baseline microagents are written into .openhands/microagents",
                "recommended first-run check: aistackd doctor ready --frontend openhands",
                project_local_skill_note(self.name),
                "baseline operator tools are not synced for OpenHands in v1; use the repo's shared tools manually when needed",
            ),
        )

    def apply(
        self,
        project_root: Path,
        plan: FrontendAdapterPlan,
        skill_contents: Mapping[str, str],
        tool_contents: Mapping[str, str],
    ) -> tuple[str, ...]:
        del tool_contents

        written_paths: list[str] = []
        provider_config_path = project_root / plan.provider_config_path
        write_toml_atomic(provider_config_path, plan.provider_payload)
        written_paths.append(str(provider_config_path))

        for managed_path in plan.managed_paths:
            if managed_path.kind != "skill":
                continue
            skill_name = Path(managed_path.path).stem
            target_path = project_root / managed_path.path
            write_text_atomic(target_path, _render_openhands_microagent(skill_name, skill_contents[skill_name]))
            written_paths.append(str(target_path))

        return tuple(written_paths)

    def cleanup(
        self,
        project_root: Path,
        managed_paths: Sequence[ManagedPath],
    ) -> tuple[str, ...]:
        """Remove stale managed OpenHands content while preserving unrelated files."""
        changed_paths: list[str] = []
        root = project_root.resolve()

        for managed_path in managed_paths:
            target_path = root / managed_path.path
            if delete_file_if_exists(target_path):
                changed_paths.append(str(target_path))
            changed_paths.extend(prune_empty_directories(target_path.parent, root))

        return tuple(changed_paths)


def _render_openhands_microagent(skill_name: str, skill_contents: str) -> str:
    """Convert a synced baseline skill into a conservative OpenHands microagent body."""
    body = _strip_frontmatter(skill_contents).strip()
    title = skill_name.replace("-", " ").title()
    return f"# {title}\n\n{body}\n"


def _strip_frontmatter(contents: str) -> str:
    """Remove YAML-style frontmatter when present."""
    lines = contents.splitlines()
    if not lines or lines[0].strip() != "---":
        return contents

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip()
    return contents
