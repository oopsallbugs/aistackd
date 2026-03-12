"""Live llmfit source-adapter tests."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aistackd.models.sources import recommend_models, search_models
from aistackd.state.host import HostBackendInstallation, HostStateStore


class ModelSourceTests(unittest.TestCase):
    def test_search_models_accepts_llmfit_json_payload(self) -> None:
        payload = {
            "models": [
                {
                    "name": "TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-Distill",
                    "description": "glm family model",
                    "context_length": 131072,
                    "best_quant": "Q4_K_M",
                    "provider": "TeichAI",
                    "runtime": "llama.cpp",
                }
            ]
        }
        with patch(
            "aistackd.models.llmfit.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=("llmfit", "search", "glm", "--json"),
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            ),
        ):
            results = search_models("glm")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "teichai-glm-4.7-flash-claude-opus-4.5-distill")
        self.assertEqual(results[0].quantization, "q4_k_m")

    def test_search_models_falls_back_to_llmfit_table_output(self) -> None:
        output = """
=== Search Results for 'glm' ===
Found 1 model(s)

│ Status │ Model                                            │ Provider │ Size │ Score │ tok/s est. │ Quant  │ Runtime   │ Mode │ Mem % │ Context │
│ --     │ TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-Distill    │ TeichAI  │ 7B   │ -     │ -          │ Q4_K_M │ llama.cpp │ GPU  │ -     │ 128k    │
""".strip()
        with patch(
            "aistackd.models.llmfit.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=("llmfit", "search", "glm", "--json"),
                returncode=0,
                stdout=output,
                stderr="",
            ),
        ):
            results = search_models("glm")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].context_window, 131072)
        self.assertEqual(results[0].quantization, "q4_k_m")

    def test_search_models_returns_empty_when_llmfit_reports_no_results(self) -> None:
        with patch(
            "aistackd.models.llmfit.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=("llmfit", "search", "missing", "--json"),
                returncode=0,
                stdout="No models found matching 'missing'\n",
                stderr="",
            ),
        ):
            results = search_models("missing")

        self.assertEqual(results, ())

    def test_recommend_models_preserves_rank_order(self) -> None:
        payload = {
            "models": [
                {
                    "name": "First/Model",
                    "description": "first result",
                    "context_length": 65536,
                    "best_quant": "Q4_K_M",
                },
                {
                    "name": "Second/Model",
                    "description": "second result",
                    "context_length": 32768,
                    "best_quant": "Q4_K_M",
                },
            ]
        }
        with patch(
            "aistackd.models.llmfit.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=("llmfit", "recommend", "--json"),
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            ),
        ):
            results = recommend_models()

        self.assertEqual([result.recommended_rank for result in results], [1, 2])

    def test_search_models_prepends_managed_llama_cpp_bin_to_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
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
            captured_env: dict[str, str] = {}

            def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
                nonlocal captured_env
                captured_env = dict(kwargs["env"])
                return subprocess.CompletedProcess(
                    args=("llmfit", "search", "glm", "--json"),
                    returncode=0,
                    stdout=json.dumps({"models": []}),
                    stderr="",
                )

            with patch("aistackd.models.llmfit.subprocess.run", side_effect=fake_run):
                search_models("glm", project_root=project_root)

            self.assertEqual(captured_env["PATH"].split(os.pathsep)[0], str(backend_bin))
