"""Atomic file I/O helpers for repo-owned state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def load_json_object(path: Path) -> dict[str, object]:
    """Load a JSON object from disk, returning an empty object when absent."""
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_text_atomic(path: Path, contents: str) -> None:
    """Write text atomically to avoid partial state updates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(contents)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Write a JSON object atomically."""
    write_text_atomic(path, json.dumps(payload, indent=2) + "\n")


def delete_file_if_exists(path: Path) -> bool:
    """Delete a file if it exists."""
    if not path.exists():
        return False
    if path.is_dir():
        raise ValueError(f"{path} is a directory; expected a file")
    path.unlink()
    return True


def prune_empty_directories(start_dir: Path, stop_at: Path) -> tuple[str, ...]:
    """Remove empty directories up to but not including ``stop_at``."""
    removed_paths: list[str] = []
    current_dir = start_dir.resolve()
    stop_dir = stop_at.resolve()

    while current_dir != stop_dir and current_dir.exists():
        if not current_dir.is_dir():
            break
        try:
            next(current_dir.iterdir())
        except StopIteration:
            current_dir.rmdir()
            removed_paths.append(str(current_dir))
            current_dir = current_dir.parent
            continue
        break

    return tuple(removed_paths)
