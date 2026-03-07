"""llmfit-backed model discovery and operator workflow helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aistackd.models.selection import derive_model_name_from_artifact_name, infer_quantization_from_artifact_name

LLMFIT_BINARY_NAME = "llmfit"


class LlmfitCommandError(RuntimeError):
    """Raised when llmfit discovery commands cannot be executed successfully."""


def resolve_llmfit_binary(llmfit_binary: str = LLMFIT_BINARY_NAME) -> str:
    """Resolve the llmfit binary path or raise a stable error."""
    path_candidate = Path(llmfit_binary).expanduser()
    if path_candidate.anchor or "/" in llmfit_binary:
        if path_candidate.exists():
            return str(path_candidate.resolve())
    else:
        resolved = shutil.which(llmfit_binary)
        if resolved is not None:
            return resolved
    raise LlmfitCommandError(f"'{llmfit_binary}' was not found on PATH")


def run_llmfit_json_command(
    subcommand: tuple[str, ...],
    *,
    llmfit_binary: str = LLMFIT_BINARY_NAME,
) -> tuple[tuple[str, ...], object]:
    """Run one llmfit JSON command and return the parsed payload."""
    resolved_binary = resolve_llmfit_binary(llmfit_binary)
    command = (resolved_binary, *subcommand, "--json")

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise LlmfitCommandError(f"failed to run llmfit command: {exc}") from exc

    raw_output = _combine_output(completed.stdout, completed.stderr)
    payload = parse_json_first_value(raw_output)
    if completed.returncode != 0:
        raise LlmfitCommandError(
            f"llmfit command '{' '.join(subcommand)}' exited with code {completed.returncode}"
        )
    if payload is None and subcommand and subcommand[0] == "search":
        if "no models found" in raw_output.lower():
            return command, []
        table_entries = parse_search_table_output(raw_output)
        if table_entries:
            return command, {"models": table_entries}
    if payload is None:
        raise LlmfitCommandError(
            f"unable to parse llmfit JSON output for command '{' '.join(subcommand)}'"
        )
    return command, payload


def launch_llmfit_browser(*, llmfit_binary: str = LLMFIT_BINARY_NAME) -> tuple[tuple[str, ...], int]:
    """Launch the native llmfit TUI in the current terminal."""
    resolved_binary = resolve_llmfit_binary(llmfit_binary)
    command = (resolved_binary,)
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        raise LlmfitCommandError(f"failed to launch llmfit browser: {exc}") from exc
    return command, int(completed.returncode)


def parse_json_first_value(payload_text: str) -> object | None:
    """Parse the first JSON value from text that may include mixed logs."""
    text = (payload_text or "").strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except ValueError:
        pass

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        return value
    return None


def extract_model_entries(payload: object) -> tuple[dict[str, object], ...]:
    """Extract llmfit model entries from a JSON payload."""
    if isinstance(payload, (list, tuple)):
        return tuple(entry for entry in payload if isinstance(entry, dict))
    if not isinstance(payload, dict):
        return ()

    for key in ("models", "results", "items", "recommendations", "data"):
        value = payload.get(key)
        entries = extract_model_entries(value)
        if entries:
            return entries

    return (payload,) if _looks_like_model_entry(payload) else ()


def parse_search_table_output(payload_text: str) -> tuple[dict[str, object], ...]:
    """Parse llmfit's tabular search output when --json misbehaves."""
    entries: list[dict[str, object]] = []
    for line in payload_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("│"):
            continue
        cells = [cell.strip() for cell in stripped.strip("│").split("│")]
        if len(cells) != 11 or cells[1] in {"Model", ""}:
            continue
        model_name = cells[1]
        provider = cells[2]
        size = cells[3]
        quantization = cells[6]
        runtime = cells[7]
        context = cells[10]
        entries.append(
            {
                "name": model_name,
                "provider": provider,
                "summary": f"provider={provider} size={size} runtime={runtime or '-'}",
                "context_length": _parse_human_context_window(context),
                "quantization": quantization,
                "tags": [provider, runtime] if runtime and runtime != "-" else [provider],
            }
        )
    return tuple(entries)


def model_name_from_entry(entry: dict[str, object]) -> str | None:
    """Extract a stable model identifier from one llmfit result entry."""
    for key in ("name", "id", "model", "model_id", "slug", "filename", "file_name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return derive_model_name_from_artifact_name(value)
    return None


def model_summary_from_entry(entry: dict[str, object]) -> str:
    """Extract a short summary from one llmfit result entry."""
    for key in ("summary", "description", "desc", "blurb", "title", "use_case"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "llmfit catalog entry"


def model_context_window_from_entry(entry: dict[str, object]) -> int:
    """Extract the context window from one llmfit result entry."""
    for key in ("context_window", "context_length", "context", "max_context", "max_context_window"):
        value = entry.get(key)
        if isinstance(value, int) and value > 0:
            return value
    metadata = entry.get("metadata")
    if isinstance(metadata, dict):
        for key in ("context_window", "context_length", "context"):
            value = metadata.get(key)
            if isinstance(value, int) and value > 0:
                return value
    return 0


def model_quantization_from_entry(entry: dict[str, object]) -> str:
    """Extract quantization metadata from one llmfit result entry."""
    for key in ("quantization", "quant", "gguf_quantization", "file_type", "best_quant"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

    for key in ("filename", "file_name", "name", "id", "model"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return infer_quantization_from_artifact_name(value)
    return "unknown"


def model_tags_from_entry(entry: dict[str, object]) -> tuple[str, ...]:
    """Extract stable tags from one llmfit result entry."""
    tags: list[str] = []
    for key in ("tags", "categories", "traits"):
        value = entry.get(key)
        tags.extend(_flatten_strings(value))
    for key in ("provider", "category", "runtime", "runtime_label"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            tags.append(value)

    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = tag.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return tuple(deduped)


def _combine_output(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stdout, stderr) if part and part.strip()]
    return "\n".join(parts)


def _looks_like_model_entry(payload: dict[str, object]) -> bool:
    return model_name_from_entry(payload) is not None


def _flatten_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _flatten_strings(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            yield from _flatten_strings(nested)


def _parse_human_context_window(value: str) -> int:
    text = value.strip().lower()
    if not text or text == "-":
        return 0
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1024
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1024 * 1024
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0
