"""Structured event logging for runtime diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Dict

LOG_ENV_FLAG = "AI_STACK_LOG_EVENTS"
EVENT_SCHEMA_VERSION = 1


def events_enabled() -> bool:
    """Return True when structured event emission is enabled."""
    return os.environ.get(LOG_ENV_FLAG, "").strip() == "1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_event(event: str, level: str = "info", **fields: Any) -> None:
    """
    Emit one structured event as a single JSON line to stderr.

    Emission is disabled by default and enabled with:
    AI_STACK_LOG_EVENTS=1
    """
    if not events_enabled():
        return

    payload: Dict[str, Any] = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "ts": _utc_now_iso(),
        "event": event,
        "level": level,
    }
    payload.update(fields)
    print(f"[ai_stack.event] {json.dumps(payload, sort_keys=True)}", file=sys.stderr)


__all__ = ["EVENT_SCHEMA_VERSION", "LOG_ENV_FLAG", "emit_event", "events_enabled"]
