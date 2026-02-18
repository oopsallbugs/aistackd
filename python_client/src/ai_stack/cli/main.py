"""Shared CLI helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional


def extract_context_size(model_info: Dict[str, Any]) -> Optional[int]:
    """Best-effort extraction across llama.cpp /props variants."""
    candidate_keys = {"context_length", "n_ctx", "ctx_size", "context_size", "n_ctx_train"}
    stack = [model_info]
    seen = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if not isinstance(current, dict):
            continue
        for key, value in current.items():
            if key in candidate_keys and isinstance(value, int):
                return value
            if isinstance(value, dict):
                stack.append(value)
    return None
