"""Reference read-only filesystem tools adapter."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ai_stack.integrations.core.errors import IntegrationError
from ai_stack.integrations.core.types import (
    IntegrationContext,
    IntegrationRuntimeConfig,
    IntegrationSmokeResult,
    IntegrationValidationResult,
)


class ReadOnlyFilesystemToolAdapter:
    """Reference tools adapter restricted to read-only operations under project root."""

    name = "tools.readonly_filesystem"

    def __init__(self, root: Optional[Path] = None):
        self._root_override = Path(root).resolve() if root is not None else None

    def _root(self, context: IntegrationContext) -> Path:
        return self._root_override or context.project_root.resolve()

    def _resolve_within_root(self, context: IntegrationContext, relative_path: str) -> Path:
        requested = Path(relative_path)
        if requested.is_absolute():
            raise IntegrationError("Absolute paths are not allowed")

        root = self._root(context)
        resolved = (root / requested).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise IntegrationError("Path escapes project root") from exc
        return resolved

    def validate(self, context: IntegrationContext) -> IntegrationValidationResult:
        root = self._root(context)
        messages: List[str] = []
        if not root.exists():
            messages.append(f"project root does not exist: {root}")
        elif not root.is_dir():
            messages.append(f"project root is not a directory: {root}")
        return IntegrationValidationResult(ok=not messages, messages=messages)

    def build_runtime_config(self, context: IntegrationContext) -> IntegrationRuntimeConfig:
        root = self._root(context)
        return IntegrationRuntimeConfig(
            name=self.name,
            values={
                "root": str(root),
                "read_only": True,
            },
        )

    def smoke_test(self, context: IntegrationContext) -> IntegrationSmokeResult:
        root = self._root(context)
        try:
            count = len(self.list_files(context=context, relative_dir="."))
            return IntegrationSmokeResult(ok=True, details=f"root ready ({count} files indexed)")
        except Exception as exc:
            return IntegrationSmokeResult(ok=False, details=f"filesystem smoke test failed: {exc}")

    def read_text(self, *, context: IntegrationContext, relative_path: str, encoding: str = "utf-8") -> str:
        path = self._resolve_within_root(context, relative_path)
        if not path.exists():
            raise IntegrationError(f"File not found: {relative_path}")
        if not path.is_file():
            raise IntegrationError(f"Not a file: {relative_path}")
        return path.read_text(encoding=encoding)

    def list_files(self, *, context: IntegrationContext, relative_dir: str = ".") -> List[str]:
        directory = self._resolve_within_root(context, relative_dir)
        if not directory.exists():
            raise IntegrationError(f"Directory not found: {relative_dir}")
        if not directory.is_dir():
            raise IntegrationError(f"Not a directory: {relative_dir}")

        root = self._root(context)
        files = []
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                files.append(str(path.relative_to(root)))
        return files

    def write_text(self, *, context: IntegrationContext, relative_path: str, content: str) -> None:
        _ = (context, relative_path, content)
        raise PermissionError("ReadOnlyFilesystemToolAdapter does not allow write operations")


__all__ = ["ReadOnlyFilesystemToolAdapter"]
