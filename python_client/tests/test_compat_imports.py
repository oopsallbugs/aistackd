from __future__ import annotations

import ai_stack.__main__ as ai_stack_main


def test_compat_imports_still_work() -> None:
    import ai_stack.cli as cli
    from ai_stack.core.config import config
    from ai_stack.stack.manager import SetupManager

    assert callable(cli.setup_cli)
    assert callable(cli.start_server_cli)
    assert callable(cli.status_cli)
    assert callable(cli.stop_server_cli)
    assert callable(cli.download_model_cli)
    assert callable(cli.check_deps_cli)
    assert callable(cli.uninstall_cli)
    assert callable(cli.sync_opencode_config_cli)
    assert hasattr(config, "paths")
    assert isinstance(SetupManager.__name__, str)


def test_python_module_dispatch_routes_command_and_args(monkeypatch) -> None:
    called = {}

    def _fake_server_stop(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(ai_stack_main, "stop_server_cli", _fake_server_stop)

    rc = ai_stack_main.main(["server-stop", "--help"])

    assert rc == 0
    assert called["argv"] == ["--help"]


def test_python_module_dispatch_accepts_setup_stack(monkeypatch) -> None:
    called = {}

    def _fake_setup():
        called["ok"] = True
        return 0

    monkeypatch.setattr(ai_stack_main, "setup_cli", _fake_setup)

    rc = ai_stack_main.main(["setup-stack"])

    assert rc == 0
    assert called["ok"] is True


def test_python_module_dispatch_accepts_sync_opencode_config(monkeypatch) -> None:
    called = {}

    def _fake_sync(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(ai_stack_main, "sync_opencode_config_cli", _fake_sync)

    rc = ai_stack_main.main(["sync-opencode-config", "--dry-run"])

    assert rc == 0
    assert called["argv"] == ["--dry-run"]
