"""Atomic file I/O helpers for repo-owned state."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path


def load_json_object(path: Path) -> dict[str, object]:
    """Load a JSON object from disk, returning an empty object when absent."""
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_toml_object(path: Path) -> dict[str, object]:
    """Load a TOML object from disk, returning an empty object when absent."""
    if not path.exists():
        return {}

    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a TOML table")
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


def write_executable_text_atomic(path: Path, contents: str) -> None:
    """Write text atomically and mark the resulting file executable."""
    write_text_atomic(path, contents)
    path.chmod(0o755)


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Write a JSON object atomically."""
    write_text_atomic(path, json.dumps(payload, indent=2) + "\n")


def write_toml_atomic(path: Path, payload: dict[str, object]) -> None:
    """Write a TOML object atomically."""
    write_text_atomic(path, _serialize_toml_document(payload))


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


def _serialize_toml_document(payload: Mapping[str, object]) -> str:
    """Serialize a subset of TOML sufficient for repo-managed config."""
    lines: list[str] = []
    _write_toml_table(lines, (), payload)
    if not lines:
        return ""
    return "\n".join(lines).rstrip() + "\n"


def _write_toml_table(
    lines: list[str],
    prefix: tuple[str, ...],
    table: Mapping[str, object],
) -> None:
    scalar_items: list[tuple[str, object]] = []
    nested_tables: list[tuple[str, Mapping[str, object]]] = []

    for key, value in table.items():
        if isinstance(value, Mapping):
            nested_tables.append((key, value))
            continue
        scalar_items.append((key, value))

    if prefix:
        if scalar_items or not nested_tables:
            lines.append(f"[{_format_toml_table_path(prefix)}]")
            for key, value in scalar_items:
                lines.append(f"{_format_toml_key(key)} = {_format_toml_value(value)}")
    else:
        for key, value in scalar_items:
            lines.append(f"{_format_toml_key(key)} = {_format_toml_value(value)}")

    for key, value in nested_tables:
        if lines and lines[-1] != "":
            lines.append("")
        _write_toml_table(lines, prefix + (key,), value)


def _format_toml_table_path(parts: Sequence[str]) -> str:
    """Format a TOML table path from key segments."""
    return ".".join(_format_toml_key(part) for part in parts)


def _format_toml_key(key: str) -> str:
    """Format a TOML key, quoting when needed."""
    if key and all(character.isalnum() or character in {"_", "-"} for character in key):
        return key
    return json.dumps(key)


def _format_toml_value(value: object) -> str:
    """Format a scalar TOML value."""
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("TOML does not support NaN or infinite floats")
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    raise ValueError(f"unsupported TOML value: {value!r}")
