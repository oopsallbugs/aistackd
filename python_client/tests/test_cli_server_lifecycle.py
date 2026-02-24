from __future__ import annotations

import json
from types import SimpleNamespace

import ai_stack.cli.server as cli_server


def _fake_config(repo_root):
    return SimpleNamespace(
        paths=SimpleNamespace(project_root=repo_root),
        server=SimpleNamespace(llama_url="http://127.0.0.1:8080"),
    )


def test_start_detached_server_writes_pid_file(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    manager_calls = {}

    class _Manager:
        def start_server(self, model_path, stdout=None, stderr=None):
            manager_calls["model_path"] = model_path
            manager_calls["stdout"] = stdout
            manager_calls["stderr"] = stderr
            return SimpleNamespace(pid=4321)

    monkeypatch.setattr(cli_server, "config", _fake_config(repo_root))

    cli_server._start_detached_server(_Manager(), "models/demo.gguf")

    pid_file = repo_root / ".ai_stack" / "server.pid"
    assert pid_file.exists()
    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    assert payload["pid"] == 4321
    assert payload["model_path"] == "models/demo.gguf"
    assert payload["endpoint"] == "http://127.0.0.1:8080"
    assert manager_calls["stdout"] is manager_calls["stderr"]
    assert manager_calls["stdout"] is not None
    assert (repo_root / "server.log").exists()


def test_stop_server_cli_uses_managed_pid_file(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    runtime_dir = repo_root / ".ai_stack"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "server.pid").write_text(json.dumps({"pid": 2468}), encoding="utf-8")
    stopped = {}

    def _record_stop(pid: int, timeout_seconds: float = 8.0) -> bool:
        stopped["pid"] = pid
        stopped["timeout_seconds"] = timeout_seconds
        return True

    monkeypatch.setattr(cli_server, "config", _fake_config(repo_root))
    monkeypatch.setattr(cli_server, "_is_process_running", lambda pid: pid == 2468)
    monkeypatch.setattr(cli_server, "_terminate_process", _record_stop)

    cli_server.stop_server_cli([])

    assert stopped["pid"] == 2468
    assert not (runtime_dir / "server.pid").exists()


def test_stop_server_cli_cleans_stale_pid_file(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    runtime_dir = repo_root / ".ai_stack"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "server.pid").write_text(json.dumps({"pid": 9999}), encoding="utf-8")

    monkeypatch.setattr(cli_server, "config", _fake_config(repo_root))
    monkeypatch.setattr(cli_server, "_is_process_running", lambda pid: False)

    cli_server.stop_server_cli([])

    assert not (runtime_dir / "server.pid").exists()


def test_stop_server_cli_handles_malformed_pid_file(monkeypatch, tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    runtime_dir = repo_root / ".ai_stack"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "server.pid").write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(cli_server, "config", _fake_config(repo_root))

    cli_server.stop_server_cli([])

    out = capsys.readouterr().out
    assert "No managed detached server found" in out


def test_server_status_wrapper_unexpected_error_is_user_safe(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli_server.server_status_cmd,
        "status_cli",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("status exploded")),
    )

    try:
        cli_server.status_cli()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    out = capsys.readouterr().out
    assert "Server status failed unexpectedly: status exploded" in out
    assert "Please retry and check logs." in out
