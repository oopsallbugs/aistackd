"""Socket-free control-plane admin helper tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.control_plane.admin import (
    AdminApiError,
    activate_model_admin,
    build_runtime_admin_payload,
    install_model_admin,
    parse_optional_json_request_body,
    recommend_models_admin,
    search_models_admin,
)
from aistackd.state.host import HostStateStore


class ControlPlaneAdminTests(unittest.TestCase):
    def test_parse_optional_json_request_body_allows_empty_body(self) -> None:
        self.assertEqual(parse_optional_json_request_body(b""), {})

    def test_build_runtime_admin_payload_reports_service_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HostStateStore(Path(tmpdir))
            payload = build_runtime_admin_payload(store, _service_config())

        self.assertEqual(payload["service"]["responses_base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(payload["runtime"]["backend"], "llama.cpp")
        self.assertEqual(payload["runtime"]["backend_status"], "missing")
        self.assertEqual(payload["runtime"]["installed_models"], [])

    def test_search_and_recommend_models_admin_use_llmfit(self) -> None:
        with patch(
            "aistackd.models.llmfit.subprocess.run",
            side_effect=_fake_llmfit_search_then_recommend_subprocess_run,
        ):
            search_payload = search_models_admin({"query": "glm"})
            recommend_payload = recommend_models_admin({})

        self.assertEqual(search_payload["source"], "llmfit")
        self.assertGreaterEqual(len(search_payload["models"]), 1)
        self.assertEqual(search_payload["models"][0]["name"], "glm-4.7-flash-claude-4.5-opus-q4-k-m")
        self.assertEqual(recommend_payload["source"], "llmfit")
        self.assertEqual(recommend_payload["models"][0]["recommended_rank"], 1)

    def test_install_and_activate_model_admin_from_explicit_gguf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            gguf_path = _create_fake_gguf(project_root, "Admin-Model-Q4_K_M.gguf")

            install_payload = install_model_admin(
                project_root,
                {
                    "model": "admin-model-q4-k-m",
                    "gguf_path": str(gguf_path),
                    "activate": True,
                },
            )

            self.assertEqual(install_payload["action"], "installed")
            self.assertEqual(install_payload["model"]["source"], "local")
            self.assertEqual(install_payload["active_model"], "admin-model-q4-k-m")
            self.assertEqual(install_payload["activation_state"], "ready")
            self.assertTrue(Path(install_payload["model"]["artifact_path"]).exists())

            activation_payload = activate_model_admin(project_root, {"model": "admin-model-q4-k-m"})
            self.assertEqual(activation_payload["action"], "activated")
            self.assertEqual(activation_payload["runtime"]["active_model"], "admin-model-q4-k-m")

    def test_install_model_admin_supports_llmfit_download_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            llmfit_download_root = project_root / "llmfit-downloads"

            def fake_llmfit_download(
                command: list[str] | tuple[str, ...],
                *,
                check: bool = False,
                capture_output: bool = True,
                text: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                if command[1] == "search":
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "models": [
                                    {
                                        "name": "admin-glm-q4-k-m",
                                        "summary": "admin llmfit model",
                                        "context_window": 32768,
                                        "quantization": "q4_k_m",
                                    }
                                ]
                            }
                        ),
                        stderr="",
                    )
                self.assertIn("--quant", command)
                self.assertIn("Q4_K_M", command)
                self.assertIn("--budget", command)
                self.assertIn("12", command)
                artifact_path = _create_fake_gguf(llmfit_download_root, "Admin-GLM.Q4_K_M.gguf")
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout=json.dumps({"artifact_path": str(artifact_path)}),
                    stderr="",
                )

            with patch("aistackd.models.llmfit.subprocess.run", side_effect=fake_llmfit_download):
                install_payload = install_model_admin(
                    project_root,
                    {
                        "model": "admin-glm-q4-k-m",
                        "quant": "Q4_K_M",
                        "budget_gb": 12,
                    },
                )

            self.assertEqual(install_payload["action"], "installed")
            self.assertEqual(install_payload["model"]["source"], "llmfit")
            self.assertEqual(install_payload["model"]["acquisition_method"], "llmfit_download")
            self.assertEqual(install_payload["acquisition"]["source"], "llmfit")
            self.assertTrue(Path(install_payload["model"]["artifact_path"]).exists())

    def test_install_model_admin_rejects_nonpositive_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(AdminApiError) as excinfo:
                install_model_admin(Path(tmpdir), {"model": "admin-glm-q4-k-m", "budget_gb": 0})

        self.assertEqual(excinfo.exception.status.value, 400)
        self.assertIn("budget_gb must be a positive number", excinfo.exception.message)

    def test_activate_model_admin_rejects_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(AdminApiError) as excinfo:
                activate_model_admin(Path(tmpdir), {"model": "missing-model"})

        self.assertEqual(excinfo.exception.status.value, 400)
        self.assertIn("is not installed", excinfo.exception.message)


def _service_config() -> object:
    from aistackd.runtime.host import HostServiceConfig

    return HostServiceConfig()


def _fake_llmfit_search_then_recommend_subprocess_run(
    command: list[str] | tuple[str, ...],
    *,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    args = tuple(command)
    executable_name = Path(args[0]).name
    if executable_name == "llmfit" and args[1] == "search":
        payload = {
            "models": [
                {
                    "name": "glm-4.7-flash-claude-4.5-opus-q4-k-m",
                    "summary": "GLM search result",
                    "context_window": 65536,
                    "quantization": "q4_k_m",
                    "tags": ["glm", "reasoning"],
                }
            ]
        }
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(payload), stderr="")
    if executable_name == "llmfit" and args[1] == "recommend":
        payload = {
            "models": [
                {
                    "name": "qwen2.5-coder-7b-instruct-q4-k-m",
                    "summary": "recommended qwen",
                    "context_window": 32768,
                    "quantization": "q4_k_m",
                    "tags": ["code"],
                    "recommended_rank": 1,
                }
            ]
        }
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(payload), stderr="")
    raise AssertionError(f"unexpected llmfit command: {args}")


def _create_fake_gguf(root: Path, filename: str) -> Path:
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_root / filename
    artifact_path.write_bytes(b"GGUF\x00test-model\n")
    return artifact_path
