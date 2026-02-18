"""Shared CLI helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def print_cli_header(title: str) -> None:
    print("=" * 60)
    print(title)
    print("=" * 60)


def print_divider() -> None:
    print("\n" + "=" * 60)


def print_section(title: str) -> None:
    print(f"\n{title}")


def print_bullet_list(items: Iterable[str], prefix: str = "  • ") -> None:
    for item in items:
        print(f"{prefix}{item}")


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


__all__ = [
    "extract_context_size",
    "print_bullet_list",
    "print_cli_header",
    "print_divider",
    "print_section",
]
