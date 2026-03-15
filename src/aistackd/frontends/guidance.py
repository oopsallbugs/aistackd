"""Shared frontend launch and config guidance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrontendGuidance:
    """Operator-facing guidance for one frontend target."""

    config_path: str
    launch_command: str
    api_key_hint: str


def build_frontend_guidance(frontend: str, api_key_env: str) -> FrontendGuidance:
    """Return shared config and launch guidance for one frontend."""
    if frontend == "codex":
        return FrontendGuidance(
            config_path=".codex/config.toml",
            launch_command="codex",
            api_key_hint=f"launch Codex from a shell where {api_key_env} is exported",
        )
    if frontend == "opencode":
        return FrontendGuidance(
            config_path="opencode.json",
            launch_command="opencode",
            api_key_hint=f"launch OpenCode from a shell where {api_key_env} is exported",
        )
    if frontend == "openhands":
        return FrontendGuidance(
            config_path=".openhands/config.toml",
            launch_command="openhands --config-file .openhands/config.toml",
            api_key_hint=(
                f"export LLM_API_KEY from {api_key_env} before launching OpenHands, "
                "or mirror the same value in the OpenHands settings UI"
            ),
        )
    raise ValueError(f"unsupported frontend '{frontend}'")
