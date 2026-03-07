"""Frontend integration exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from aistackd.frontends.catalog import SUPPORTED_FRONTENDS, normalize_frontend_targets

__all__ = [
    "CURRENT_SYNC_MANIFEST_SCHEMA_VERSION",
    "CURRENT_SYNC_OWNERSHIP_SCHEMA_VERSION",
    "SUPPORTED_FRONTENDS",
    "SyncChange",
    "SyncError",
    "SyncManifest",
    "SyncOwnershipManifest",
    "SyncRequest",
    "SyncWriteResult",
    "apply_sync_manifest",
    "evaluate_sync_manifest",
    "normalize_frontend_targets",
]

_SYNC_EXPORTS = {
    "CURRENT_SYNC_MANIFEST_SCHEMA_VERSION",
    "CURRENT_SYNC_OWNERSHIP_SCHEMA_VERSION",
    "SyncChange",
    "SyncError",
    "SyncManifest",
    "SyncOwnershipManifest",
    "SyncRequest",
    "SyncWriteResult",
    "apply_sync_manifest",
    "evaluate_sync_manifest",
}


def __getattr__(name: str) -> Any:
    """Lazily expose sync-layer exports without forcing import cycles."""
    if name in _SYNC_EXPORTS:
        module = import_module("aistackd.frontends.sync")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
