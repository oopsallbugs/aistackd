"""Integration framework entrypoints."""

from __future__ import annotations

from pathlib import Path

from ai_stack.core.config import config
from ai_stack.integrations.core import (
    AdapterNotFoundError,
    AdapterRegistrationError,
    AdapterSmokeTestError,
    AdapterValidationError,
    IntegrationAdapter,
    IntegrationContext,
    IntegrationError,
    IntegrationRuntimeConfig,
    IntegrationSmokeResult,
    IntegrationValidationResult,
    get_adapter,
    list_adapters,
    register_adapter,
)
from ai_stack.integrations.adapters.opencode import OpenCodeAdapter
from ai_stack.integrations.adapters.openhands import OpenHandsAdapter
from ai_stack.integrations.adapters.tools import ReadOnlyFilesystemToolAdapter
from ai_stack.integrations.frontends.opencode import (
    OpenCodeSyncResult,
    sync_opencode_global_config_with_defaults,
)
from ai_stack.integrations.frontends.openhands import (
    OpenHandsSyncResult,
    sync_openhands_global_config_with_defaults,
)
from ai_stack.llm import create_client


def build_integration_context() -> IntegrationContext:
    """Build default integration context from active runtime configuration."""
    return IntegrationContext(
        project_root=config.paths.project_root,
        llama_api_url=config.server.llama_url,
        default_model=config.model.default_model,
        create_client=create_client,
    )


def register_default_adapters() -> None:
    """Register built-in Phase D adapters."""
    existing = set(list_adapters())

    if OpenCodeAdapter.name not in existing:
        register_adapter(OpenCodeAdapter())

    if OpenHandsAdapter.name not in existing:
        register_adapter(OpenHandsAdapter())

    if ReadOnlyFilesystemToolAdapter.name not in existing:
        register_adapter(ReadOnlyFilesystemToolAdapter())


def sync_opencode_project_config(path: Path | None = None) -> Path:
    """
    Generate/refresh project-level opencode.json from current ai-stack runtime.

    Returns the written config path.
    """
    register_default_adapters()
    adapter = get_adapter("opencode")
    write_config = getattr(adapter, "write_project_config", None)
    if not callable(write_config):
        raise AdapterValidationError("opencode adapter does not support project config export")
    context = build_integration_context()
    return write_config(context, path=path)


def sync_opencode_global_config(
    *,
    global_path: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    sync_skills: bool = False,
    skills_dir: Path | None = None,
    dry_run: bool = False,
) -> OpenCodeSyncResult:
    """Generate/refresh global opencode config from current ai-stack runtime."""
    register_default_adapters()
    return sync_opencode_global_config_with_defaults(
        build_context=build_integration_context,
        global_path=global_path,
        sync_tools=sync_tools,
        sync_agents=sync_agents,
        sync_skills=sync_skills,
        skills_dir=skills_dir,
        dry_run=dry_run,
    )


def sync_openhands_global_config(
    *,
    global_path: Path | None = None,
    mcp_json_path: Path | None = None,
    skills_dir: Path | None = None,
    sync_tools: bool = False,
    sync_agents: bool = False,
    sync_skills: bool = False,
    emit_mcp_json: bool = False,
    dry_run: bool = False,
) -> OpenHandsSyncResult:
    """Generate/refresh global OpenHands config from ai-stack runtime."""
    register_default_adapters()
    return sync_openhands_global_config_with_defaults(
        build_context=build_integration_context,
        global_path=global_path,
        mcp_json_path=mcp_json_path,
        skills_dir=skills_dir,
        sync_tools=sync_tools,
        sync_agents=sync_agents,
        sync_skills=sync_skills,
        emit_mcp_json=emit_mcp_json,
        dry_run=dry_run,
    )


__all__ = [
    "AdapterNotFoundError",
    "AdapterRegistrationError",
    "AdapterSmokeTestError",
    "AdapterValidationError",
    "IntegrationAdapter",
    "IntegrationContext",
    "IntegrationError",
    "IntegrationRuntimeConfig",
    "IntegrationSmokeResult",
    "IntegrationValidationResult",
    "OpenHandsAdapter",
    "OpenHandsSyncResult",
    "OpenCodeAdapter",
    "OpenCodeSyncResult",
    "ReadOnlyFilesystemToolAdapter",
    "build_integration_context",
    "get_adapter",
    "list_adapters",
    "register_adapter",
    "register_default_adapters",
    "sync_openhands_global_config",
    "sync_opencode_global_config",
    "sync_opencode_project_config",
]
