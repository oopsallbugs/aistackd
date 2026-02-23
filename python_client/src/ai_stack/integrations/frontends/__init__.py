"""External frontend sync/export entrypoints."""

from ai_stack.integrations.frontends.opencode import (
    OpenCodeSyncResult,
    sync_opencode_global_config,
    sync_opencode_global_config_with_defaults,
)

__all__ = [
    "OpenCodeSyncResult",
    "sync_opencode_global_config",
    "sync_opencode_global_config_with_defaults",
]
