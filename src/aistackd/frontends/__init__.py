"""Frontend integration exports."""

from aistackd.frontends.catalog import SUPPORTED_FRONTENDS, normalize_frontend_targets
from aistackd.frontends.sync import (
    CURRENT_SYNC_MANIFEST_SCHEMA_VERSION,
    CURRENT_SYNC_OWNERSHIP_SCHEMA_VERSION,
    SyncChange,
    SyncError,
    SyncManifest,
    SyncOwnershipManifest,
    SyncRequest,
    SyncWriteResult,
    apply_sync_manifest,
    evaluate_sync_manifest,
)

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
