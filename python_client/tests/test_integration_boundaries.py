from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path("python_client/src/ai_stack")


def _iter_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_core_runtime_layers_do_not_import_integrations() -> None:
    runtime_dirs = [
        PROJECT_ROOT / "core",
        PROJECT_ROOT / "huggingface",
        PROJECT_ROOT / "models",
        PROJECT_ROOT / "stack",
        PROJECT_ROOT / "llama",
    ]

    offenders = []
    for directory in runtime_dirs:
        for file_path in directory.rglob("*.py"):
            for imported in _iter_imports(file_path):
                if imported.startswith("ai_stack.integrations"):
                    offenders.append((str(file_path), imported))

    assert offenders == []


def test_cli_layer_may_import_integration_entrypoints_only() -> None:
    cli_dir = PROJECT_ROOT / "cli"
    offenders = []

    for file_path in cli_dir.rglob("*.py"):
        for imported in _iter_imports(file_path):
            if imported.startswith("ai_stack.integrations.core"):
                offenders.append((str(file_path), imported))

    assert offenders == []


def test_integrations_do_not_import_forbidden_runtime_internals() -> None:
    integrations_dir = PROJECT_ROOT / "integrations"
    forbidden_prefixes = (
        "ai_stack.stack.manager",
        "ai_stack.stack.hf_downloads",
        "ai_stack.models.registry",
        "ai_stack.huggingface",
        "ai_stack.cli",
    )

    offenders = []
    for file_path in integrations_dir.rglob("*.py"):
        for imported in _iter_imports(file_path):
            if imported.startswith(forbidden_prefixes):
                offenders.append((str(file_path), imported))

    assert offenders == []


def test_integrations_use_llm_facade_not_llama_client_module() -> None:
    integrations_dir = PROJECT_ROOT / "integrations"

    offenders = []
    for file_path in integrations_dir.rglob("*.py"):
        for imported in _iter_imports(file_path):
            if imported.startswith("ai_stack.llama.client"):
                offenders.append((str(file_path), imported))

    assert offenders == []
