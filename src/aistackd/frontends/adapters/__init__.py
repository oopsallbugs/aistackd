"""Frontend adapter registry."""

from __future__ import annotations

from aistackd.frontends.adapters.base import FrontendAdapter
from aistackd.frontends.adapters.codex import CodexAdapter
from aistackd.frontends.adapters.openhands import OpenHandsAdapter
from aistackd.frontends.adapters.opencode import OpenCodeAdapter

_FRONTEND_ADAPTERS: dict[str, FrontendAdapter] = {
    "codex": CodexAdapter(),
    "opencode": OpenCodeAdapter(),
    "openhands": OpenHandsAdapter(),
}


def get_frontend_adapter(frontend: str) -> FrontendAdapter:
    """Return the registered adapter for ``frontend``."""
    try:
        return _FRONTEND_ADAPTERS[frontend]
    except KeyError as exc:
        raise ValueError(f"unsupported frontend adapter: {frontend}") from exc


__all__ = ["get_frontend_adapter"]
