"""Frontend sync scaffold types."""

from __future__ import annotations

from dataclasses import dataclass

from aistackd.frontends.catalog import normalize_frontend_targets


@dataclass(frozen=True)
class SyncRequest:
    """Minimal sync request for the scaffold."""

    targets: tuple[str, ...]
    dry_run: bool = False

    @classmethod
    def create(cls, targets: tuple[str, ...] | None = None, dry_run: bool = False) -> "SyncRequest":
        return cls(targets=normalize_frontend_targets(targets), dry_run=dry_run)
