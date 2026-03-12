"""CLI tests for scaffold and contract slices."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import tomllib
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aistackd.cli.main import build_parser, main
from aistackd.models.llmfit import LlmfitCommandError
from aistackd.runtime.host import HostServiceConfig
from aistackd.runtime.hardware import CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION, HardwareProfile, LlmfitDetectionResult
from aistackd.state.layout import COMMAND_GROUPS
from aistackd.state.host import HostBackendInstallation, HostStateStore


def invoke(argv: list[str]) -> tuple[int, str, str]:
    """Invoke the CLI entrypoint and capture stdio."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class CLITests(unittest.TestCase):
    def test_help_lists_documented_command_groups(self) -> None:
        help_text = build_parser().format_help()
        for command_name in COMMAND_GROUPS:
            self.assertIn(command_name, help_text)

    def test_doctor_reports_scaffold_as_json(self) -> None:
        exit_code, stdout, stderr = invoke(["doctor", "--format", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")

        payload = json.loads(stdout)
        self.assertEqual(payload["command_groups"], list(COMMAND_GROUPS))

        scaffold_checks = {entry["label"]: entry["exists"] for entry in payload["scaffold_paths"]}
        self.assertTrue(scaffold_checks["package_root"])
        self.assertTrue(scaffold_checks["ci_workflow"])
        self.assertTrue(scaffold_checks["shared_skills"])
        self.assertTrue(scaffold_checks["shared_tools"])

    def test_doctor_ready_reports_opencode_frontend_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--role-hint",
                    "client",
                    "--activate",
                ]
            )
            invoke(["sync", "--project-root", tmpdir, "--target", "opencode", "--write"])

            with (
                patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
                patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_remote_client_urlopen),
            ):
                exit_code, stdout, stderr = invoke(
                    ["doctor", "ready", "--project-root", tmpdir, "--frontend", "opencode", "--format", "json"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["frontend"], "opencode")
            self.assertEqual(payload["active_profile"], "remote")
            self.assertTrue(payload["remote_validation"]["ok"])
            self.assertTrue(payload["smoke"]["ok"])
            sync_labels = {entry["label"]: entry["detail"] for entry in payload["sync_checks"]}
            self.assertIn("project_local_skill_roots", sync_labels)
            self.assertIn(".agents/skills", sync_labels["project_local_skill_roots"])
            self.assertEqual(
                sync_labels["project_local_skill_provenance_file"],
                "aistackd-skill-provenance.json",
            )

    def test_doctor_ready_reports_openhands_frontend_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--role-hint",
                    "client",
                    "--activate",
                ]
            )
            invoke(["sync", "--project-root", tmpdir, "--target", "openhands", "--write"])

            with (
                patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
                patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_remote_client_urlopen),
            ):
                exit_code, stdout, stderr = invoke(
                    ["doctor", "ready", "--project-root", tmpdir, "--frontend", "openhands", "--format", "json"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["frontend"], "openhands")
            self.assertEqual(payload["active_profile"], "remote")
            sync_labels = {entry["label"]: entry["detail"] for entry in payload["sync_checks"]}
            self.assertIn(".openhands/microagents", sync_labels["project_local_skill_roots"])

    def test_doctor_ready_reports_missing_frontend_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--role-hint",
                    "client",
                    "--activate",
                ]
            )

            with patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False):
                exit_code, stdout, stderr = invoke(
                    ["doctor", "ready", "--project-root", tmpdir, "--frontend", "opencode", "--format", "json"]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("run 'aistackd sync --target opencode --write'", "\n".join(payload["errors"]))

    def test_profiles_add_list_show_and_activate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--role-hint",
                    "host",
                    "--activate",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("created profile 'local'", stdout)
            self.assertIn("active_profile: local", stdout)

            exit_code, stdout, stderr = invoke(["profiles", "list", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("* local: http://127.0.0.1:8000", stdout)
            self.assertIn("api_key_env=AISTACKD_API_KEY", stdout)
            self.assertIn("model=local-model", stdout)

            exit_code, stdout, stderr = invoke(["profiles", "show", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("name: local", stdout)
            self.assertIn("active: yes", stdout)
            self.assertIn("model: local-model", stdout)
            self.assertIn("role_hint: host", stdout)

    def test_profiles_validate_reports_missing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = invoke(
                [
                    "profiles",
                    "add",
                    "remote-host",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://10.0.0.50:8080",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("AISTACKD_REMOTE_API_KEY", None)
                exit_code, stdout, stderr = invoke(["profiles", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stderr, "")
            self.assertIn("profile: remote-host", stdout)
            self.assertIn("status: invalid", stdout)
            self.assertIn("readiness_error: api key environment variable 'AISTACKD_REMOTE_API_KEY' is not set or empty", stdout)

    def test_profiles_validate_succeeds_when_api_key_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                exit_code, stdout, stderr = invoke(["profiles", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("profile: local", stdout)
            self.assertIn("status: ok", stdout)

    def test_client_reports_active_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--role-hint",
                    "host",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(["client", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("client runtime config", stdout)
            self.assertIn("active_profile: local", stdout)
            self.assertIn("responses_base_url: http://127.0.0.1:8000/v1", stdout)
            self.assertIn("model: local-model", stdout)
            self.assertIn("frontend_targets: codex, opencode, openhands", stdout)

    def test_client_validate_reports_remote_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--role-hint",
                    "client",
                    "--activate",
                ]
            )

            with (
                patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
                patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_remote_client_urlopen),
            ):
                exit_code, stdout, stderr = invoke(["client", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("client validation", stdout)
            self.assertIn("status: ok", stdout)
            self.assertIn("health_status_code: 200", stdout)
            self.assertIn("runtime_status_code: 200", stdout)

    def test_client_validate_reports_remote_auth_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--activate",
                ]
            )

            with (
                patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "bad-key"}, clear=False),
                patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_remote_client_unauthorized_urlopen),
            ):
                exit_code, stdout, stderr = invoke(["client", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stderr, "")
            self.assertIn("status: invalid", stdout)
            self.assertIn("health returned status 401", stdout)

    def test_client_smoke_runs_remote_responses_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--role-hint",
                    "client",
                    "--activate",
                ]
            )

            with (
                patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
                patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_remote_smoke_urlopen),
            ):
                exit_code, stdout, stderr = invoke(["client", "smoke", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("client smoke", stdout)
            self.assertIn("active_profile: remote", stdout)
            self.assertIn("output_text: Hello from llama-server", stdout)

    def test_client_tool_demo_executes_local_tool_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--role-hint",
                    "client",
                    "--activate",
                ]
            )

            with (
                patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
                patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_remote_tool_demo_urlopen),
            ):
                exit_code, stdout, stderr = invoke(["client", "tool-demo", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("client tool demo", stdout)
            self.assertIn("tool_calls: 1", stdout)
            self.assertIn("final_output_text: The time is available.", stdout)

    def test_client_models_install_proxies_remote_admin_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "remote",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_REMOTE_API_KEY",
                    "--model",
                    "remote-model",
                    "--activate",
                ]
            )

            with (
                patch.dict(os.environ, {"AISTACKD_REMOTE_API_KEY": "test-key"}, clear=False),
                patch("aistackd.runtime.remote.request.urlopen", side_effect=_fake_remote_install_urlopen),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "client",
                        "models",
                        "install",
                        "glm-remote",
                        "--project-root",
                        tmpdir,
                        "--quant",
                        "Q4_K_M",
                        "--budget",
                        "12",
                        "--activate",
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "installed")
            self.assertEqual(payload["model"]["source"], "llmfit")
            self.assertEqual(payload["active_model"], "glm-remote")

    def test_models_show_list_and_set_active_profile_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(["models", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("profile: local", stdout)
            self.assertIn("model: local-model", stdout)

            exit_code, stdout, stderr = invoke(["models", "list", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("* local: local-model", stdout)

            exit_code, stdout, stderr = invoke(
                ["models", "set", "refined-model", "--project-root", tmpdir, "--format", "json"]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "updated")
            self.assertEqual(payload["profile"]["profile"], "local")
            self.assertEqual(payload["profile"]["model"], "refined-model")

            exit_code, stdout, stderr = invoke(["models", "--project-root", tmpdir, "--format", "json"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["profile"], "local")
            self.assertEqual(payload["model"], "refined-model")
            self.assertTrue(payload["active"])

    def test_models_search_install_activate_and_host_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            gguf_path = _create_fake_gguf(Path(tmpdir), "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
            with patch(
                "aistackd.models.llmfit.subprocess.run",
                side_effect=_fake_llmfit_recommend_subprocess_run,
            ):
                exit_code, stdout, stderr = invoke(["models", "recommend", "--project-root", tmpdir, "--format", "json"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertGreaterEqual(len(payload["models"]), 2)
            self.assertEqual(payload["models"][0]["source"], "llmfit")

            exit_code, stdout, stderr = invoke(
                [
                    "models",
                    "install",
                    "qwen2.5-coder-7b-instruct-q4-k-m",
                    "--project-root",
                    tmpdir,
                    "--gguf-path",
                    str(gguf_path),
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "installed")
            self.assertEqual(payload["model"]["source"], "local")
            self.assertEqual(payload["model"]["acquisition_method"], "explicit_local_gguf")
            self.assertTrue(Path(payload["model"]["artifact_path"]).exists())
            self.assertIsNone(payload["active_model"])
            self.assertEqual(payload["acquisition"]["source"], "local")

            exit_code, stdout, stderr = invoke(["models", "installed", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("installed_models: 1", stdout)
            self.assertIn("qwen2.5-coder-7b-instruct-q4-k-m: source=local", stdout)
            self.assertIn("method=explicit_local_gguf", stdout)

            exit_code, stdout, stderr = invoke(
                [
                    "models",
                    "activate",
                    "qwen2.5-coder-7b-instruct-q4-k-m",
                    "--project-root",
                    tmpdir,
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "activated")
            self.assertEqual(payload["runtime"]["active_model"], "qwen2.5-coder-7b-instruct-q4-k-m")
            self.assertEqual(payload["runtime"]["activation_state"], "ready")

            exit_code, stdout, stderr = invoke(["host", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("host runtime state", stdout)
            self.assertIn("backend_status: missing", stdout)
            self.assertIn("backend_process_status: not_started", stdout)
            self.assertIn("active_model: qwen2.5-coder-7b-instruct-q4-k-m", stdout)
            self.assertIn("source=local method=explicit_local_gguf", stdout)
            self.assertIn("installed_models: 1", stdout)

            exit_code, stdout, stderr = invoke(["host", "validate", "--project-root", tmpdir, "--format", "json"])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertIn(
                "api key environment variable 'AISTACKD_API_KEY' is not set or empty",
                payload["errors"],
            )
            self.assertIn(
                "no backend installation is configured for host runtime",
                payload["errors"],
            )

            backend_root = _create_fake_backend_root(Path(tmpdir))

            with patch(
                "aistackd.runtime.prereqs.detect_hardware_with_llmfit",
                return_value=_fake_llmfit_detection(),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "host",
                        "inspect",
                        "--project-root",
                        tmpdir,
                        "--backend-root",
                        str(backend_root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertTrue(payload["hardware_detection"]["ok"])
            self.assertEqual(payload["acquisition_plan"]["flavor"], "cuda")
            self.assertTrue(payload["backend_discovery"]["found"])
            self.assertEqual(payload["backend_discovery"]["discovery_mode"], "explicit_root")

            with patch(
                "aistackd.runtime.prereqs.detect_hardware_with_llmfit",
                return_value=_fake_llmfit_detection(),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "host",
                        "acquire-backend",
                        "--project-root",
                        tmpdir,
                        "--backend-root",
                        str(backend_root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "adopted")
            self.assertTrue(payload["backend_installation"]["server_binary"].endswith("llama-server"))
            self.assertEqual(payload["acquisition_plan"]["flavor"], "cuda")

            with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                exit_code, stdout, stderr = invoke(["host", "validate", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("host validation", stdout)
            self.assertIn("status: ok", stdout)
            self.assertIn("backend_status: configured", stdout)
            self.assertIn("backend_process_status: not_started", stdout)
            self.assertIn("server_binary:", stdout)
            self.assertIn("base_url: http://127.0.0.1:8000", stdout)
            self.assertIn("backend_base_url: http://127.0.0.1:8011", stdout)

            running_process = _fake_running_backend_process(Path(tmpdir))
            with (
                patch("aistackd.cli.commands.host.launch_managed_backend_process", return_value=running_process) as launch_mock,
                patch("aistackd.cli.commands.host.stop_managed_backend_process") as stop_mock,
                patch("aistackd.cli.commands.host.serve_control_plane") as serve_mock,
            ):
                with patch.dict(os.environ, {"AISTACKD_API_KEY": "test-key"}, clear=False):
                    exit_code, stdout, stderr = invoke(["host", "serve", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("control plane serving", stdout)
            self.assertIn("server_binary:", stdout)
            self.assertIn("backend_base_url: http://127.0.0.1:8011", stdout)
            self.assertIn("backend_pid: 4242", stdout)
            self.assertIn("backend_context_size: 24576", stdout)
            self.assertIn("backend_predict_limit: 4096", stdout)
            self.assertIn("active_model: qwen2.5-coder-7b-instruct-q4-k-m", stdout)
            launch_mock.assert_called_once()
            stop_mock.assert_called_once()
            serve_mock.assert_called_once()

    def test_models_install_discovers_local_gguf_for_uncatalogued_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_models_root = Path(tmpdir) / "models"
            local_models_root.mkdir(parents=True, exist_ok=True)
            discovered_path = _create_fake_gguf(local_models_root, "custom-local-model.Q5_K_M.gguf")

            exit_code, stdout, stderr = invoke(
                [
                    "models",
                    "install",
                    "custom-local-model",
                    "--project-root",
                    tmpdir,
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["model"]["source"], "local")
            self.assertEqual(payload["model"]["acquisition_method"], "discovered_local_gguf")
            self.assertNotEqual(Path(payload["model"]["artifact_path"]), discovered_path)
            self.assertTrue(Path(payload["model"]["artifact_path"]).exists())
            self.assertEqual(payload["acquisition"]["attempts"][0]["strategy"], "local_search")
            self.assertTrue(payload["acquisition"]["attempts"][0]["ok"])

    def test_models_search_uses_live_llmfit_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "aistackd.models.llmfit.subprocess.run",
                side_effect=_fake_llmfit_search_subprocess_run,
            ):
                exit_code, stdout, stderr = invoke(
                    ["models", "search", "glm", "--project-root", tmpdir, "--format", "json"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["source"], "llmfit")
            self.assertEqual(len(payload["models"]), 2)
            self.assertEqual(payload["models"][0]["name"], "teichai-glm-4.7-flash-claude-opus-4.5-distill")
            self.assertEqual(payload["models"][0]["quantization"], "q4_k_m")

    def test_host_stop_reports_stopped_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_store = SimpleNamespace(
                load_runtime_state=unittest.mock.Mock(
                    side_effect=[
                        SimpleNamespace(
                            backend_process_status="running",
                            control_plane_process_status="not_started",
                            control_plane_process=None,
                        ),
                        SimpleNamespace(
                            backend_process_status="stopped",
                            control_plane_process_status="not_started",
                            control_plane_process=None,
                        ),
                    ]
                )
            )
            stopped_record = SimpleNamespace(
                pid=4242,
                log_path=str(Path(tmpdir) / ".aistackd" / "host" / "logs" / "llama-cpp.log"),
                as_dict=lambda: {
                    "status": "stopped",
                    "pid": 4242,
                },
            )

            with (
                patch("aistackd.cli.commands.host.HostStateStore", return_value=fake_store),
                patch("aistackd.cli.commands.host.stop_current_managed_backend_process", return_value=stopped_record),
            ):
                exit_code, stdout, stderr = invoke(["host", "stop", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("managed backend stopped", stdout)
            self.assertIn("before_status: running", stdout)
            self.assertIn("after_status: stopped", stdout)
            self.assertIn("backend_pid: 4242", stdout)

    def test_host_stop_service_reports_stopped_control_plane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_store = SimpleNamespace(
                load_runtime_state=unittest.mock.Mock(
                    side_effect=[
                        SimpleNamespace(
                            backend_process_status="running",
                            control_plane_process_status="running",
                            control_plane_process=SimpleNamespace(pid=3131),
                        ),
                        SimpleNamespace(
                            backend_process_status="running",
                            control_plane_process_status="stopped",
                            control_plane_process=SimpleNamespace(pid=3131),
                        ),
                    ]
                )
            )
            stopped_record = SimpleNamespace(
                pid=3131,
                log_path=str(Path(tmpdir) / ".aistackd" / "host" / "logs" / "control-plane.log"),
                as_dict=lambda: {"status": "stopped", "pid": 3131},
            )

            with (
                patch("aistackd.cli.commands.host.HostStateStore", return_value=fake_store),
                patch("aistackd.cli.commands.host.stop_current_control_plane_process", return_value=stopped_record),
            ):
                exit_code, stdout, stderr = invoke(["host", "stop", "--project-root", tmpdir, "--service"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("managed control-plane stopped", stdout)
            self.assertIn("before_control_plane_status: running", stdout)
            self.assertIn("after_control_plane_status: stopped", stdout)
            self.assertIn("control_plane_pid: 3131", stdout)

    def test_host_restart_reports_restarted_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_store = SimpleNamespace()
            validation_result = SimpleNamespace(
                ok=True,
                errors=(),
                runtime=SimpleNamespace(backend_process_status="running", control_plane_process_status="not_started"),
                service=HostServiceConfig(),
            )
            running_process = SimpleNamespace(
                record=SimpleNamespace(
                    pid=5151,
                    base_url="http://127.0.0.1:8011",
                    log_path=str(Path(tmpdir) / ".aistackd" / "host" / "logs" / "llama-cpp.log"),
                    context_size=24576,
                    predict_limit=4096,
                    model="qwen2.5-coder-7b-instruct-q4-k-m",
                    as_dict=lambda: {
                        "status": "running",
                        "pid": 5151,
                        "context_size": 24576,
                        "predict_limit": 4096,
                    },
                )
            )

            with (
                patch("aistackd.cli.commands.host.HostStateStore", return_value=fake_store),
                patch("aistackd.cli.commands.host.validate_backend_runtime", return_value=validation_result),
                patch("aistackd.cli.commands.host.restart_managed_backend_process", return_value=running_process),
            ):
                exit_code, stdout, stderr = invoke(["host", "restart", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("managed backend restarted", stdout)
            self.assertIn("before_status: running", stdout)
            self.assertIn("after_status: running", stdout)
            self.assertIn("backend_pid: 5151", stdout)
            self.assertIn("backend_context_size: 24576", stdout)
            self.assertIn("backend_predict_limit: 4096", stdout)

    def test_host_start_reports_started_control_plane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_store = SimpleNamespace()
            validation_result = SimpleNamespace(
                ok=True,
                errors=(),
                runtime=SimpleNamespace(control_plane_process_status="not_started"),
                service=HostServiceConfig(),
            )
            running_process = SimpleNamespace(
                record=SimpleNamespace(
                    pid=6161,
                    log_path=str(Path(tmpdir) / ".aistackd" / "host" / "logs" / "control-plane.log"),
                    as_dict=lambda: {"status": "starting", "pid": 6161},
                )
            )

            with (
                patch("aistackd.cli.commands.host.HostStateStore", return_value=fake_store),
                patch("aistackd.cli.commands.host.validate_host_runtime", return_value=validation_result),
                patch("aistackd.cli.commands.host.launch_control_plane_process", return_value=running_process),
            ):
                exit_code, stdout, stderr = invoke(["host", "start", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("managed control-plane started", stdout)
            self.assertIn("control_plane_pid: 6161", stdout)
            self.assertIn("base_url: http://127.0.0.1:8000", stdout)

    def test_host_restart_service_reports_restarted_control_plane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_store = SimpleNamespace()
            validation_result = SimpleNamespace(
                ok=True,
                errors=(),
                runtime=SimpleNamespace(control_plane_process_status="running"),
                service=HostServiceConfig(),
            )
            running_process = SimpleNamespace(
                record=SimpleNamespace(
                    pid=7171,
                    log_path=str(Path(tmpdir) / ".aistackd" / "host" / "logs" / "control-plane.log"),
                    as_dict=lambda: {"status": "starting", "pid": 7171},
                )
            )

            with (
                patch("aistackd.cli.commands.host.HostStateStore", return_value=fake_store),
                patch("aistackd.cli.commands.host.validate_host_runtime", return_value=validation_result),
                patch("aistackd.cli.commands.host.stop_current_control_plane_process"),
                patch("aistackd.cli.commands.host.launch_control_plane_process", return_value=running_process),
            ):
                exit_code, stdout, stderr = invoke(["host", "restart", "--project-root", tmpdir, "--service"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("managed control-plane restarted", stdout)
            self.assertIn("before_control_plane_status: running", stdout)
            self.assertIn("after_control_plane_status: starting", stdout)
            self.assertIn("control_plane_pid: 7171", stdout)

    def test_models_browse_imports_all_new_ggufs_after_successful_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            watch_root = project_root / "llmfit-cache"
            backend_bin = project_root / ".aistackd" / "host" / "backends" / "llama.cpp" / "build" / "bin"
            backend_bin.mkdir(parents=True)
            HostStateStore(project_root).save_backend_installation(
                HostBackendInstallation(
                    backend="llama.cpp",
                    acquisition_method="downloaded_source_build",
                    backend_root=str(backend_bin.parent),
                    server_binary=str(backend_bin / "llama-server"),
                    cli_binary=str(backend_bin / "llama-cli"),
                    configured_at="2026-03-12T00:00:00+00:00",
                )
            )
            captured_path = ""

            def fake_browse_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[object]:
                nonlocal captured_path
                captured_path = str(dict(kwargs["env"])["PATH"])
                _create_fake_gguf(watch_root, "GLM-4.7-Flash-Claude-4.5-Opus.q4_k_m.gguf")
                _create_fake_gguf(watch_root, "Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf", payload=b"GGUF\x00qwen\n")
                return subprocess.CompletedProcess(args=command, returncode=0, stdout=None, stderr=None)

            with patch("aistackd.models.llmfit.subprocess.run", side_effect=fake_browse_run):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "browse",
                        "--project-root",
                        tmpdir,
                        "--watch-root",
                        str(watch_root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["llmfit_exit_code"], 0)
            self.assertEqual(payload["imports"]["imported_count"], 2)
            self.assertEqual(captured_path.split(os.pathsep)[0], str(backend_bin))

            exit_code, stdout, stderr = invoke(["models", "installed", "--project-root", tmpdir, "--format", "json"])
            self.assertEqual(exit_code, 0)
            installed_payload = json.loads(stdout)
            self.assertEqual(len(installed_payload["models"]), 2)
            self.assertIsNone(installed_payload["active_model"])
            self.assertTrue(all(model["source"] == "llmfit" for model in installed_payload["models"]))

    def test_models_browse_skips_import_when_llmfit_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            watch_root = project_root / "llmfit-cache"

            def fake_failed_browse(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[object]:
                _create_fake_gguf(watch_root, "GLM-4.7-Flash-Claude-4.5-Opus.q4_k_m.gguf")
                return subprocess.CompletedProcess(args=command, returncode=2, stdout=None, stderr=None)

            with patch("aistackd.models.llmfit.subprocess.run", side_effect=fake_failed_browse):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "browse",
                        "--project-root",
                        tmpdir,
                        "--watch-root",
                        str(watch_root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["imports"]["imported_count"], 0)

            exit_code, stdout, stderr = invoke(["models", "installed", "--project-root", tmpdir, "--format", "json"])
            self.assertEqual(exit_code, 0)
            installed_payload = json.loads(stdout)
            self.assertEqual(installed_payload["models"], [])

    def test_models_import_llmfit_imports_detected_watch_root_ggufs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_root = Path(tmpdir) / "llmfit-cache"
            _create_fake_gguf(watch_root, "GLM-4.7-Flash-Claude-4.5-Opus.q4_k_m.gguf")
            _create_fake_gguf(watch_root, "Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf", payload=b"GGUF\x00qwen\n")

            with patch(
                "aistackd.cli.commands.models.iter_llmfit_watch_roots",
                return_value=(watch_root.resolve(),),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "import-llmfit",
                        "--project-root",
                        tmpdir,
                        "--watch-root",
                        str(watch_root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["imports"]["imported_count"], 2)

    def test_models_install_uses_llmfit_download_with_quant_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            llmfit_root = Path(tmpdir) / "llmfit-downloads"
            backend_bin = project_root / ".aistackd" / "host" / "backends" / "llama.cpp" / "build" / "bin"
            backend_bin.mkdir(parents=True)
            HostStateStore(project_root).save_backend_installation(
                HostBackendInstallation(
                    backend="llama.cpp",
                    acquisition_method="downloaded_source_build",
                    backend_root=str(backend_bin.parent),
                    server_binary=str(backend_bin / "llama-server"),
                    cli_binary=str(backend_bin / "llama-cli"),
                    configured_at="2026-03-12T00:00:00+00:00",
                )
            )
            captured_paths: list[str] = []

            def fake_llmfit_run(
                command: tuple[str, ...],
                **kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                captured_paths.append(str(dict(kwargs["env"])["PATH"]))
                if command[1] == "search":
                    return _fake_llmfit_search_result(
                        command,
                        model_name="glm-4.7-flash-claude-4.5-opus-q4-k-m",
                    )
                if command[1] == "download":
                    self.assertIn("--quant", command)
                    self.assertIn("Q4_K_M", command)
                    self.assertIn("--budget", command)
                    self.assertIn("12", command)
                    artifact_path = _create_fake_gguf(llmfit_root, "GLM-4.7-Flash-Claude-4.5-Opus.Q4_K_M.gguf")
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout=json.dumps({"artifact_path": str(artifact_path)}),
                        stderr="",
                    )
                raise AssertionError(f"unexpected llmfit command: {command}")

            with patch("aistackd.models.llmfit.subprocess.run", side_effect=fake_llmfit_run):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "install",
                        "glm-4.7-flash-claude-4.5-opus-q4-k-m",
                        "--project-root",
                        tmpdir,
                        "--quant",
                        "Q4_K_M",
                        "--budget",
                        "12",
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["model"]["source"], "llmfit")
            self.assertEqual(payload["model"]["acquisition_method"], "llmfit_download")
            self.assertEqual(payload["acquisition"]["source"], "llmfit")
            self.assertTrue(Path(payload["model"]["artifact_path"]).exists())
            self.assertTrue(captured_paths)
            self.assertTrue(all(path_value.split(os.pathsep)[0] == str(backend_bin) for path_value in captured_paths))

    def test_models_install_fails_when_llmfit_download_finds_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_root = Path(tmpdir) / "llmfit-watch"

            def fake_llmfit_run(
                command: tuple[str, ...],
                **kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                if command[1] == "search":
                    return _fake_llmfit_search_result(
                        command,
                        model_name="glm-4.7-flash-claude-4.5-opus-q4-k-m",
                    )
                if command[1] == "download":
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout=json.dumps({"status": "ok"}),
                        stderr="",
                    )
                raise AssertionError(f"unexpected llmfit command: {command}")

            with (
                patch("aistackd.models.llmfit.subprocess.run", side_effect=fake_llmfit_run),
                patch(
                    "aistackd.models.acquisition.iter_llmfit_watch_roots",
                    return_value=(watch_root.resolve(),),
                ),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "install",
                        "glm-4.7-flash-claude-4.5-opus-q4-k-m",
                        "--project-root",
                        tmpdir,
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("llmfit download did not identify a GGUF artifact", stderr)

    def test_models_install_fails_when_llmfit_download_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_root = Path(tmpdir) / "llmfit-watch"

            def fake_llmfit_run(
                command: tuple[str, ...],
                **kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                if command[1] == "search":
                    return _fake_llmfit_search_result(
                        command,
                        model_name="glm-4.7-flash-claude-4.5-opus-q4-k-m",
                    )
                if command[1] == "download":
                    _create_fake_gguf(watch_root, "GLM-4.7-Flash-Claude-4.5-Opus.Q4_K_M.gguf")
                    _create_fake_gguf(watch_root, "Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf", payload=b"GGUF\x00qwen\n")
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout=json.dumps({"status": "ok"}),
                        stderr="",
                    )
                raise AssertionError(f"unexpected llmfit command: {command}")

            with (
                patch("aistackd.models.llmfit.subprocess.run", side_effect=fake_llmfit_run),
                patch(
                    "aistackd.models.acquisition.iter_llmfit_watch_roots",
                    return_value=(watch_root.resolve(),),
                ),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "install",
                        "glm-4.7-flash-claude-4.5-opus-q4-k-m",
                        "--project-root",
                        tmpdir,
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("llmfit download produced multiple GGUF candidates", stderr)

    def test_models_install_fails_when_llmfit_download_fails_without_explicit_hf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "aistackd.models.llmfit.subprocess.run",
                side_effect=_fake_failed_llmfit_download_after_search_subprocess_run,
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "install",
                        "glm-4.7-flash-claude-4.5-opus-q4-k-m",
                        "--project-root",
                        tmpdir,
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("llmfit command 'download glm-4.7-flash-claude-4.5-opus-q4-k-m' exited with code 2", stderr)

    def test_models_install_supports_hugging_face_url_without_model_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch(
                    "aistackd.models.acquisition.run_llmfit_download",
                    side_effect=LlmfitCommandError("llmfit command 'download glm-4.7-flash-claude-4.5-opus.q4-k-m' exited with code 2"),
                ),
                patch(
                    "aistackd.models.acquisition.subprocess.run",
                    side_effect=_fake_hf_download_subprocess_run,
                ),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "models",
                        "install",
                        "--project-root",
                        tmpdir,
                        "--hf-url",
                        (
                            "https://huggingface.co/TeichAI/"
                            "GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF"
                            "?show_file_info=glm-4.7-flash-claude-4.5-opus.q4_k_m.gguf"
                        ),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["model"]["source"], "hugging_face")
            self.assertEqual(payload["acquisition"]["source"], "hugging_face")
            self.assertEqual(payload["acquisition"]["attempts"][1]["provider"], "llmfit")
            self.assertFalse(payload["acquisition"]["attempts"][1]["ok"])
            self.assertEqual(payload["acquisition"]["attempts"][2]["provider"], "hugging_face")
            self.assertTrue(payload["acquisition"]["attempts"][2]["ok"])
            self.assertTrue(payload["model"]["model"].startswith("glm-4.7-flash-claude-4.5-opus"))

    def test_host_acquire_backend_downloads_from_llmfit_plan_when_backend_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            installation = SimpleNamespace(
                as_dict=lambda: {
                    "backend": "llama.cpp",
                    "acquisition_method": "downloaded_source_build",
                    "backend_root": str(Path(tmpdir) / ".aistackd" / "host" / "backends" / "llama.cpp" / "install"),
                    "server_binary": str(Path(tmpdir) / ".aistackd" / "host" / "backends" / "llama.cpp" / "install" / "bin" / "llama-server"),
                    "cli_binary": str(Path(tmpdir) / ".aistackd" / "host" / "backends" / "llama.cpp" / "install" / "bin" / "llama-cli"),
                    "configured_at": "2026-03-10T00:00:00+00:00",
                }
            )
            acquisition = SimpleNamespace(
                strategy="downloaded_source_build",
                installation=installation,
                attempts=(
                    SimpleNamespace(strategy="downloaded_prebuilt", ok=False, detail="no supported official prebuilt asset is pinned"),
                    SimpleNamespace(strategy="downloaded_source_build", ok=True, detail="downloaded and built source fallback"),
                ),
                to_dict=lambda: {
                    "strategy": "downloaded_source_build",
                    "installation": installation.as_dict(),
                    "attempts": [
                        {"strategy": "downloaded_prebuilt", "ok": False, "detail": "no supported official prebuilt asset is pinned"},
                        {"strategy": "downloaded_source_build", "ok": True, "detail": "downloaded and built source fallback"},
                    ],
                    "warnings": [],
                },
            )

            with (
                patch(
                    "aistackd.runtime.prereqs.detect_hardware_with_llmfit",
                    return_value=_fake_llmfit_detection(
                        backend="amd",
                        acceleration_api="rocm",
                        target="gfx1100",
                    ),
                ),
                patch("aistackd.runtime.backends.shutil.which", return_value=None),
                patch("aistackd.cli.commands.host.acquire_managed_llama_cpp_installation", return_value=acquisition),
            ):
                exit_code, stdout, stderr = invoke(
                    ["host", "acquire-backend", "--project-root", tmpdir, "--format", "json"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "acquired")
            self.assertEqual(payload["acquisition_plan"]["flavor"], "rocm")
            self.assertEqual(payload["acquisition"]["strategy"], "downloaded_source_build")
            self.assertEqual(
                payload["acquisition_plan"]["source_environment"]["HSA_OVERRIDE_GFX_VERSION"],
                "11.0.0",
            )

    def test_host_install_llmfit_reports_installed_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_result = SimpleNamespace(
                to_dict=lambda: {
                    "action": "installed",
                    "tool": {
                        "tool": "llmfit",
                        "executable_path": str(Path(tmpdir) / "bin" / "llmfit"),
                        "version": "llmfit 0.6.2",
                    },
                }
            )

            with patch("aistackd.cli.commands.host.install_tool", return_value=install_result):
                exit_code, stdout, stderr = invoke(["host", "install-llmfit", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("installed tool 'llmfit'", stdout)
            self.assertIn("version: llmfit 0.6.2", stdout)

    def test_host_bootstrap_reports_tool_installs_and_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_store = SimpleNamespace(save_backend_installation=unittest.mock.Mock(return_value=True))
            llmfit_result = SimpleNamespace(
                to_dict=lambda: {
                    "action": "installed",
                    "tool": {
                        "tool": "llmfit",
                        "executable_path": str(Path(tmpdir) / "bin" / "llmfit"),
                    },
                }
            )
            hf_result = SimpleNamespace(
                to_dict=lambda: {
                    "action": "installed",
                    "tool": {
                        "tool": "hf",
                        "executable_path": str(Path(tmpdir) / "bin" / "hf"),
                    },
                }
            )
            report = SimpleNamespace(
                acquisition_plan=SimpleNamespace(to_dict=lambda: {"flavor": "cpu"}),
                hardware_detection=SimpleNamespace(issues=(), to_dict=lambda: {"ok": True}),
                to_dict=lambda: {"ok": True, "tool_checks": [], "acquisition_plan": {"flavor": "cpu"}},
            )
            installation = SimpleNamespace(
                as_dict=lambda: {
                    "backend_root": str(Path(tmpdir) / ".aistackd" / "host" / "backends" / "llama.cpp" / "install"),
                }
            )
            acquisition = SimpleNamespace(
                installation=installation,
                to_dict=lambda: {
                    "strategy": "downloaded_prebuilt",
                },
            )

            with (
                patch("aistackd.cli.commands.host.install_tool", side_effect=[llmfit_result, hf_result]),
                patch("aistackd.cli.commands.host.inspect_host_environment", return_value=report),
                patch("aistackd.cli.commands.host.acquire_managed_llama_cpp_installation", return_value=acquisition),
                patch("aistackd.cli.commands.host.HostStateStore", return_value=fake_store),
            ):
                exit_code, stdout, stderr = invoke(["host", "bootstrap", "--project-root", tmpdir])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("host bootstrap complete", stdout)
            self.assertIn("tool=llmfit", stdout)
            self.assertIn("tool=hf", stdout)
            self.assertIn("backend_root=", stdout)

    def test_host_acquire_backend_from_prebuilt_root_creates_managed_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prebuilt_root = _create_fake_backend_root(Path(tmpdir) / "external-prebuilt")

            with patch(
                "aistackd.runtime.prereqs.detect_hardware_with_llmfit",
                return_value=_fake_llmfit_detection(),
            ):
                exit_code, stdout, stderr = invoke(
                    [
                        "host",
                        "acquire-backend",
                        "--project-root",
                        tmpdir,
                        "--prebuilt-root",
                        str(prebuilt_root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["action"], "acquired")
            self.assertEqual(payload["acquisition"]["strategy"], "prebuilt_root")
            self.assertEqual(payload["backend_installation"]["acquisition_method"], "acquired_prebuilt_root")
            self.assertIn(".aistackd/host/backends/llama.cpp/install", payload["backend_installation"]["backend_root"])
            self.assertTrue(Path(payload["backend_installation"]["server_binary"]).exists())

    def test_sync_preview_uses_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(
                ["sync", "--project-root", tmpdir, "--target", "codex", "--format", "json"]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")

            payload = json.loads(stdout)
            self.assertEqual(payload["active_profile"], "local")
            self.assertEqual(payload["mode"], "client")
            self.assertTrue(payload["dry_run"])
            self.assertEqual(len(payload["targets"]), 1)
            self.assertEqual(payload["targets"][0]["frontend"], "codex")
            self.assertEqual(payload["targets"][0]["provider_base_url"], "http://127.0.0.1:8000/v1")
            self.assertEqual(payload["targets"][0]["provider_config_path"], ".codex/config.toml")
            self.assertEqual(payload["targets"][0]["activation_mode"], "project_local")
            self.assertEqual(
                payload["targets"][0]["provider_payload"]["profiles"]["aistackd"]["model"],
                "local-model",
            )

            exit_code, stdout, stderr = invoke(["sync", "--project-root", tmpdir, "--target", "codex"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("change_summary: create=8", stdout)
            self.assertIn("change: create frontend=codex kind=provider_config path=.codex/config.toml", stdout)
            self.assertIn("change: create frontend=codex kind=tool path=.codex/tools/runtime-status.py", stdout)
            self.assertIn("change: create frontend=codex kind=tool path=.codex/tools/responses-smoke.py", stdout)
            self.assertIn("change: create frontend=codex kind=tool path=.codex/tools/runtime-wait.py", stdout)
            self.assertIn("change: create frontend=codex kind=tool path=.codex/tools/frontend-smoke.py", stdout)
            self.assertIn("change: create frontend=codex kind=tool path=.codex/tools/tool-call-demo.py", stdout)

    def test_sync_manifest_preview_reports_openhands_provider_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(
                ["sync", "--project-root", tmpdir, "--target", "openhands", "--format", "json"]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")

            payload = json.loads(stdout)
            self.assertEqual(payload["active_profile"], "local")
            self.assertEqual(payload["targets"][0]["frontend"], "openhands")
            self.assertEqual(payload["targets"][0]["provider_config_path"], ".openhands/config.toml")
            self.assertEqual(payload["targets"][0]["baseline_tools"], [])
            self.assertEqual(
                payload["targets"][0]["provider_payload"]["llm"]["model"],
                "openai/local-model",
            )

            exit_code, stdout, stderr = invoke(["sync", "--project-root", tmpdir, "--target", "openhands"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("change_summary: create=2", stdout)
            self.assertIn(
                "change: create frontend=openhands kind=provider_config path=.openhands/config.toml",
                stdout,
            )
            self.assertIn(
                "change: create frontend=openhands kind=skill path=.openhands/microagents/find-skills.md",
                stdout,
            )

    def test_sync_requires_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = invoke(["sync", "--project-root", tmpdir])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("no active profile is set", stderr)

    def test_sync_write_creates_managed_files_and_ownership_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            opencode_path = Path(tmpdir) / "opencode.json"
            opencode_path.write_text(
                json.dumps(
                    {
                        "custom": {"keep": True},
                        "provider": {"existing": {"name": "keep"}},
                        "model": "existing/default",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            invoke(
                [
                    "profiles",
                    "add",
                    "local",
                    "--project-root",
                    tmpdir,
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--api-key-env",
                    "AISTACKD_API_KEY",
                    "--model",
                    "local-model",
                    "--activate",
                ]
            )

            exit_code, stdout, stderr = invoke(["sync", "--project-root", tmpdir, "--write"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("sync write", stdout)
            self.assertIn("ownership_manifest:", stdout)
            self.assertIn(".agents/skills", stdout)
            self.assertIn(".openhands/microagents", stdout)
            self.assertIn("aistackd-skill-provenance.json", stdout)

            opencode_payload = json.loads(opencode_path.read_text(encoding="utf-8"))
            self.assertEqual(opencode_payload["custom"], {"keep": True})
            self.assertIn("existing", opencode_payload["provider"])
            self.assertIn("aistackd", opencode_payload["provider"])
            self.assertEqual(opencode_payload["model"], "aistackd/local-model")
            self.assertEqual(
                opencode_payload["provider"]["aistackd"]["options"]["apiKey"],
                "{env:AISTACKD_API_KEY}",
            )
            self.assertEqual(
                opencode_payload["provider"]["aistackd"]["models"]["local-model"]["name"],
                "local-model",
            )
            self.assertEqual(
                opencode_payload["provider"]["aistackd"]["models"]["local-model"]["limit"]["context"],
                24576,
            )
            self.assertEqual(
                opencode_payload["provider"]["aistackd"]["models"]["local-model"]["limit"]["output"],
                4096,
            )

            codex_payload = tomllib.loads(
                (Path(tmpdir) / ".codex" / "config.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(codex_payload["profile"], "aistackd")
            self.assertEqual(
                codex_payload["profiles"]["aistackd"]["model_provider"],
                "aistackd",
            )
            self.assertEqual(codex_payload["profiles"]["aistackd"]["model"], "local-model")
            self.assertEqual(
                codex_payload["model_providers"]["aistackd"]["base_url"],
                "http://127.0.0.1:8000/v1",
            )
            self.assertEqual(
                codex_payload["model_providers"]["aistackd"]["env_key"],
                "AISTACKD_API_KEY",
            )

            opencode_skill = Path(tmpdir) / ".opencode" / "skills" / "find-skills" / "SKILL.md"
            codex_skill = Path(tmpdir) / ".codex" / "skills" / "find-skills" / "SKILL.md"
            openhands_config = Path(tmpdir) / ".openhands" / "config.toml"
            openhands_microagent = Path(tmpdir) / ".openhands" / "microagents" / "find-skills.md"
            opencode_tool = Path(tmpdir) / ".opencode" / "tools" / "runtime-status.py"
            codex_tool = Path(tmpdir) / ".codex" / "tools" / "model-admin.py"
            opencode_smoke_tool = Path(tmpdir) / ".opencode" / "tools" / "responses-smoke.py"
            codex_wait_tool = Path(tmpdir) / ".codex" / "tools" / "runtime-wait.py"
            opencode_frontend_smoke_tool = Path(tmpdir) / ".opencode" / "tools" / "frontend-smoke.py"
            codex_tool_call_demo = Path(tmpdir) / ".codex" / "tools" / "tool-call-demo.py"
            self.assertTrue(opencode_skill.exists())
            self.assertTrue(codex_skill.exists())
            self.assertTrue(openhands_config.exists())
            self.assertTrue(openhands_microagent.exists())
            self.assertTrue(opencode_tool.exists())
            self.assertTrue(codex_tool.exists())
            self.assertTrue(opencode_smoke_tool.exists())
            self.assertTrue(codex_wait_tool.exists())
            self.assertTrue(opencode_frontend_smoke_tool.exists())
            self.assertTrue(codex_tool_call_demo.exists())
            self.assertIn("name: find-skills", opencode_skill.read_text(encoding="utf-8"))
            openhands_payload = tomllib.loads(openhands_config.read_text(encoding="utf-8"))
            self.assertEqual(openhands_payload["llm"]["model"], "openai/local-model")
            self.assertEqual(openhands_payload["llm"]["base_url"], "http://127.0.0.1:8000/v1")
            self.assertTrue(openhands_payload["agent"]["enable_prompt_extensions"])
            self.assertIn("# Find Skills", openhands_microagent.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_BASE_URL = "http://127.0.0.1:8000"', opencode_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_API_KEY_ENV = "AISTACKD_API_KEY"', codex_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_BASE_URL = "http://127.0.0.1:8000"', opencode_smoke_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_API_KEY_ENV = "AISTACKD_API_KEY"', codex_wait_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_ACTIVE_PROFILE = "local"', opencode_frontend_smoke_tool.read_text(encoding="utf-8"))
            self.assertIn('DEFAULT_MODEL = "local-model"', codex_tool_call_demo.read_text(encoding="utf-8"))

            ownership_manifest_path = (
                Path(tmpdir) / ".aistackd" / "sync" / "ownership_manifest.json"
            )
            ownership_payload = json.loads(ownership_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(ownership_payload["active_profile"], "local")
            self.assertEqual(len(ownership_payload["targets"]), 3)


def _create_fake_backend_root(root: Path) -> Path:
    backend_root = root / "llama.cpp"
    bin_dir = backend_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for binary_name in ("llama-server", "llama-cli"):
        path = bin_dir / binary_name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return backend_root


def _create_fake_gguf(root: Path, filename: str, *, payload: bytes = b"GGUF\x00test-model\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / filename
    artifact_path.write_bytes(payload)
    return artifact_path


def _fake_llmfit_recommend_subprocess_run(
    command: tuple[str, ...],
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    payload = {
        "models": [
            {
                "name": "qwen2.5-coder-7b-instruct-q4-k-m",
                "description": "balanced coding default",
                "context_length": 32768,
                "best_quant": "Q4_K_M",
                "provider": "llmfit",
                "runtime": "llama.cpp",
            },
            {
                "name": "llama-3.1-8b-instruct-q4-k-m",
                "description": "general-purpose instruct model",
                "context_length": 32768,
                "best_quant": "Q4_K_M",
                "provider": "llmfit",
                "runtime": "llama.cpp",
            },
        ]
    }
    return subprocess.CompletedProcess(args=command, returncode=0, stdout=json.dumps(payload), stderr="")


def _fake_llmfit_search_subprocess_run(
    command: tuple[str, ...],
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    payload = {
        "models": [
            {
                "name": "TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-Distill",
                "description": "high reasoning glm distill",
                "context_length": 131072,
                "best_quant": "Q4_K_M",
                "provider": "TeichAI",
                "runtime": "llama.cpp",
            },
            {
                "name": "THUDM/GLM-4.5-Air",
                "description": "lighter glm family model",
                "context_length": 65536,
                "best_quant": "Q4_K_M",
                "provider": "THUDM",
                "runtime": "llama.cpp",
            },
        ]
    }
    return subprocess.CompletedProcess(args=command, returncode=0, stdout=json.dumps(payload), stderr="")


def _fake_llmfit_search_result(
    command: tuple[str, ...],
    *,
    model_name: str,
) -> subprocess.CompletedProcess[str]:
    payload = {
        "models": [
            {
                "name": model_name,
                "description": "llmfit search result",
                "context_length": 131072,
                "best_quant": "Q4_K_M",
                "provider": "llmfit",
                "runtime": "llama.cpp",
            }
        ]
    }
    return subprocess.CompletedProcess(args=command, returncode=0, stdout=json.dumps(payload), stderr="")


def _fake_failed_llmfit_download_subprocess_run(
    command: tuple[str, ...],
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=command, returncode=2, stdout="", stderr="llmfit download failed")


def _fake_failed_llmfit_download_after_search_subprocess_run(
    command: tuple[str, ...],
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    if command[1] == "search":
        return _fake_llmfit_search_result(command, model_name="glm-4.7-flash-claude-4.5-opus-q4-k-m")
    if command[1] == "download":
        return _fake_failed_llmfit_download_subprocess_run(command)
    raise AssertionError(f"unexpected llmfit command: {command}")


def _fake_hf_download_subprocess_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    local_dir = Path(command[command.index("--local-dir") + 1])
    filename = command[3]
    downloaded_path = _create_fake_gguf(local_dir, filename)
    return subprocess.CompletedProcess(
        args=command,
        returncode=0,
        stdout=str(downloaded_path),
        stderr="",
    )


class _FakeUrlopenResponse:
    def __init__(self, status: int, payload: dict[str, object]) -> None:
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeErrorStream:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, *_args: object, **_kwargs: object) -> bytes:
        payload = self._payload
        self._payload = b""
        return payload

    def close(self) -> None:
        return None


def _fake_remote_client_urlopen(request_obj: object, timeout: float = 5) -> _FakeUrlopenResponse:
    url = getattr(request_obj, "full_url")
    if url.endswith("/health"):
        return _FakeUrlopenResponse(200, {"status": "ok", "active_model": "remote-model"})
    if url.endswith("/v1/models"):
        return _FakeUrlopenResponse(200, {"object": "list", "active_model": "remote-model", "data": []})
    if url.endswith("/admin/runtime"):
        return _FakeUrlopenResponse(
            200,
            {
                "runtime": {"active_model": "remote-model", "backend_status": "configured", "installed_models": []},
                "service": {"base_url": "http://127.0.0.1:8000"},
            },
        )
    if url.endswith("/v1/responses"):
        decoded = json.loads(getattr(request_obj, "data").decode("utf-8"))
        if decoded["input"] != "say hello in one short sentence":
            raise AssertionError(f"unexpected smoke payload: {decoded}")
        return _FakeUrlopenResponse(
            200,
            {
                "id": "resp_smoke",
                "model": "remote-model",
                "output_text": "Hello from llama-server",
                "output": [],
            },
        )
    raise AssertionError(f"unexpected URL: {url}")


def _fake_remote_client_unauthorized_urlopen(request_obj: object, timeout: float = 5) -> _FakeUrlopenResponse:
    body = json.dumps({"error": {"message": "missing or invalid API key"}}).encode("utf-8")
    raise urllib.error.HTTPError(
        getattr(request_obj, "full_url"),
        401,
        "Unauthorized",
        hdrs=None,
        fp=_FakeErrorStream(body),
    )


def _fake_remote_install_urlopen(request_obj: object, timeout: float = 30) -> _FakeUrlopenResponse:
    url = getattr(request_obj, "full_url")
    if not url.endswith("/admin/models/install"):
        raise AssertionError(f"unexpected URL: {url}")
    decoded = json.loads(getattr(request_obj, "data").decode("utf-8"))
    if decoded["quant"] != "Q4_K_M" or decoded["budget_gb"] != 12:
        raise AssertionError(f"unexpected install payload: {decoded}")
    return _FakeUrlopenResponse(
        200,
        {
            "action": "installed",
            "model": {
                "model": decoded["model"],
                "source": "llmfit",
                "acquisition_method": "llmfit_download",
                "artifact_path": "/managed/models/glm-remote.gguf",
            },
            "active_model": decoded["model"],
        },
    )


def _fake_remote_smoke_urlopen(request_obj: object, timeout: float = 30) -> _FakeUrlopenResponse:
    url = getattr(request_obj, "full_url")
    if not url.endswith("/v1/responses"):
        raise AssertionError(f"unexpected URL: {url}")
    payload = json.loads(getattr(request_obj, "data").decode("utf-8"))
    if payload["input"] != "say hello in one short sentence":
        raise AssertionError(f"unexpected smoke payload: {payload}")
    return _FakeUrlopenResponse(
        200,
        {
            "id": "resp_smoke",
            "model": "remote-model",
            "output_text": "Hello from llama-server",
            "output": [],
        },
    )


def _fake_remote_tool_demo_urlopen(request_obj: object, timeout: float = 30) -> _FakeUrlopenResponse:
    payload = json.loads(getattr(request_obj, "data").decode("utf-8"))
    previous_response_id = payload.get("previous_response_id")
    if previous_response_id is None:
        return _FakeUrlopenResponse(
            200,
            {
                "id": "resp_tool",
                "model": "remote-model",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_123",
                        "name": "get_local_time",
                        "arguments": "{}",
                    }
                ],
                "output_text": "",
            },
        )
    if previous_response_id != "resp_tool":
        raise AssertionError(f"unexpected previous_response_id: {previous_response_id}")
    tool_outputs = payload.get("input")
    if not isinstance(tool_outputs, list) or not tool_outputs:
        raise AssertionError(f"unexpected follow-up payload: {payload}")
    first_item = tool_outputs[0]
    if not isinstance(first_item, dict) or first_item.get("type") != "function_call_output":
        raise AssertionError(f"unexpected tool output payload: {payload}")
    return _FakeUrlopenResponse(
        200,
        {
            "id": "resp_final",
            "model": "remote-model",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "The time is available.", "annotations": []}],
                }
            ],
            "output_text": "The time is available.",
        },
    )


def _fake_running_backend_process(project_root: Path) -> SimpleNamespace:
    log_path = project_root / ".aistackd" / "host" / "logs" / "llama-cpp.log"
    return SimpleNamespace(
        record=SimpleNamespace(
            pid=4242,
            log_path=str(log_path),
            context_size=24576,
            predict_limit=4096,
        )
    )


def _fake_llmfit_detection(
    *,
    backend: str = "nvidia",
    acceleration_api: str = "cuda",
    target: str = "",
) -> LlmfitDetectionResult:
    profile = HardwareProfile(
        schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
        detector="llmfit",
        backend=backend,
        acceleration_api=acceleration_api,
        target=target,
        cmake_flags=(
            ("-DGGML_HIP=ON", f"-DGPU_TARGETS={target}")
            if acceleration_api == "rocm" and target
            else ("-DGGML_HIP=ON",)
            if acceleration_api == "rocm"
            else ("-DGGML_CUDA=ON",)
            if acceleration_api == "cuda"
            else ()
        ),
        gpu_layers=99 if acceleration_api != "cpu" else 0,
        hsa_override_gfx_version="11.0.0" if acceleration_api == "rocm" else "",
    )
    return LlmfitDetectionResult(
        detector="llmfit",
        available=True,
        ok=True,
        command=("llmfit", "system", "--json"),
        exit_code=0,
        raw_output="{}",
        raw_payload={"provider": backend},
        profile=profile,
    )
