"""External frontend sync/export entrypoints."""

from ai_stack.integrations.frontends.opencode import (
    OpenCodeSyncResult,
    sync_opencode_global_config,
    sync_opencode_global_config_with_defaults,
)
from ai_stack.integrations.frontends.openhands import (
    OpenHandsSyncResult,
    sync_openhands_global_config,
    sync_openhands_global_config_with_defaults,
)

__all__ = [
    "OpenHandsSyncResult",
    "OpenCodeSyncResult",
    "sync_openhands_global_config",
    "sync_openhands_global_config_with_defaults",
    "sync_opencode_global_config",
    "sync_opencode_global_config_with_defaults",
]
