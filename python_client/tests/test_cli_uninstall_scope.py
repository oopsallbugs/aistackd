from __future__ import annotations

from types import SimpleNamespace

import ai_stack.cli.setup as cli_setup


def test_uninstall_removes_only_repo_local_runtime_paths(monkeypatch, tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    models_dir = repo_root / "models"
    llama_cpp_dir = repo_root / "llama.cpp"
    runtime_cache = repo_root / ".ai_stack"

    models_dir.mkdir(parents=True)
    llama_cpp_dir.mkdir(parents=True)
    runtime_cache.mkdir(parents=True)
    (models_dir / "model.gguf").write_text("x", encoding="utf-8")
    (llama_cpp_dir / "build.txt").write_text("x", encoding="utf-8")
    (runtime_cache / "cache.json").write_text("{}", encoding="utf-8")

    fake_home = tmp_path / "home"
    legacy_cache = fake_home / ".cache" / "ai_stack"
    legacy_config = fake_home / ".config" / "ai_stack"
    legacy_cache.mkdir(parents=True)
    legacy_config.mkdir(parents=True)
    (legacy_config / "config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        cli_setup,
        "config",
        SimpleNamespace(
            paths=SimpleNamespace(
                models_dir=models_dir,
                llama_cpp_dir=llama_cpp_dir,
                project_root=repo_root,
            )
        ),
    )
    monkeypatch.setattr("builtins.input", lambda _: "y")

    cli_setup.uninstall_cli([])

    assert not models_dir.exists()
    assert not llama_cpp_dir.exists()
    assert not runtime_cache.exists()
    assert legacy_cache.exists()
    assert (legacy_config / "config.json").exists()
    assert capsys.readouterr().err == ""


def test_uninstall_yes_skips_confirmation_prompt(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    models_dir = repo_root / "models"
    llama_cpp_dir = repo_root / "llama.cpp"
    runtime_cache = repo_root / ".ai_stack"
    models_dir.mkdir(parents=True)
    llama_cpp_dir.mkdir(parents=True)
    runtime_cache.mkdir(parents=True)

    monkeypatch.setattr(
        cli_setup,
        "config",
        SimpleNamespace(
            paths=SimpleNamespace(
                models_dir=models_dir,
                llama_cpp_dir=llama_cpp_dir,
                project_root=repo_root,
            )
        ),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _: (_ for _ in ()).throw(AssertionError("input should not be called when --yes is set")),
    )

    cli_setup.uninstall_cli(["--yes"])

    assert not models_dir.exists()
    assert not llama_cpp_dir.exists()
    assert not runtime_cache.exists()


def test_uninstall_selective_models_only(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    models_dir = repo_root / "models"
    llama_cpp_dir = repo_root / "llama.cpp"
    runtime_cache = repo_root / ".ai_stack"
    models_dir.mkdir(parents=True)
    llama_cpp_dir.mkdir(parents=True)
    runtime_cache.mkdir(parents=True)

    monkeypatch.setattr(
        cli_setup,
        "config",
        SimpleNamespace(
            paths=SimpleNamespace(
                models_dir=models_dir,
                llama_cpp_dir=llama_cpp_dir,
                project_root=repo_root,
            )
        ),
    )

    cli_setup.uninstall_cli(["--yes", "--models"])

    assert not models_dir.exists()
    assert llama_cpp_dir.exists()
    assert runtime_cache.exists()
