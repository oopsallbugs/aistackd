from __future__ import annotations

from pathlib import Path

import pytest

from ai_stack.integrations.core.errors import IntegrationError
from ai_stack.integrations.core.types import IntegrationContext
from ai_stack.integrations.adapters.tools import ReadOnlyFilesystemToolAdapter


def _context(project_root: Path) -> IntegrationContext:
    return IntegrationContext(
        project_root=project_root,
        llama_api_url="http://127.0.0.1:8080",
        default_model="m.gguf",
        create_client=lambda **kwargs: None,
    )


def test_tools_adapter_validate_build_and_smoke(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.txt").write_text("beta", encoding="utf-8")

    adapter = ReadOnlyFilesystemToolAdapter()
    context = _context(tmp_path)

    validation = adapter.validate(context)
    runtime = adapter.build_runtime_config(context)
    smoke = adapter.smoke_test(context)

    assert validation.ok is True
    assert runtime.name == "tools.readonly_filesystem"
    assert runtime.values["read_only"] is True
    assert runtime.values["root"] == str(tmp_path.resolve())
    assert smoke.ok is True


def test_tools_adapter_read_and_list_are_root_relative(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.txt").write_text("beta", encoding="utf-8")

    adapter = ReadOnlyFilesystemToolAdapter()
    context = _context(tmp_path)

    assert adapter.read_text(context=context, relative_path="a.txt") == "alpha"
    assert adapter.list_files(context=context, relative_dir=".") == ["a.txt", "nested/b.txt"]


def test_tools_adapter_rejects_absolute_and_escape_paths(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")

    adapter = ReadOnlyFilesystemToolAdapter()
    context = _context(tmp_path)

    with pytest.raises(IntegrationError, match="Absolute paths are not allowed"):
        adapter.read_text(context=context, relative_path=str((tmp_path / "a.txt").resolve()))

    with pytest.raises(IntegrationError, match="Path escapes project root"):
        adapter.read_text(context=context, relative_path="../outside.txt")


def test_tools_adapter_rejects_mutation(tmp_path) -> None:
    adapter = ReadOnlyFilesystemToolAdapter()
    context = _context(tmp_path)

    with pytest.raises(PermissionError, match="does not allow write operations"):
        adapter.write_text(context=context, relative_path="a.txt", content="nope")


def test_tools_adapter_missing_path_errors_are_stable(tmp_path) -> None:
    adapter = ReadOnlyFilesystemToolAdapter()
    context = _context(tmp_path)

    with pytest.raises(IntegrationError, match="File not found: missing.txt"):
        adapter.read_text(context=context, relative_path="missing.txt")

    with pytest.raises(IntegrationError, match="Directory not found: missing"):
        adapter.list_files(context=context, relative_dir="missing")
