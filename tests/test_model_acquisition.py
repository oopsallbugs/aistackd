"""Managed model acquisition tests."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.models.acquisition import (
    acquire_managed_model_artifact,
    discover_local_gguf,
    import_managed_gguf_candidates,
    parse_hugging_face_url,
)
from aistackd.models.sources import local_source_model


class ModelAcquisitionTests(unittest.TestCase):
    def test_acquire_managed_model_from_explicit_gguf_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            artifact_path = _create_fake_gguf(Path(tmpdir) / "imports", "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")
            source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m")

            result = acquire_managed_model_artifact(
                project_root,
                source_model,
                explicit_gguf_path=artifact_path,
            )

            self.assertEqual(result.source, "local")
            self.assertEqual(result.acquisition_method, "explicit_local_gguf")
            self.assertTrue(Path(result.artifact_path).exists())
            self.assertEqual(result.attempts[0].strategy, "explicit_path")
            self.assertTrue(result.attempts[0].ok)

    def test_discover_local_gguf_prefers_matching_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            models_root = project_root / "models"
            nested_root = models_root / "nested"
            _create_fake_gguf(models_root, "something-else.gguf")
            expected_path = _create_fake_gguf(nested_root, "custom-local-model.Q5_K_M.gguf")

            result = discover_local_gguf(
                "custom-local-model",
                project_root=project_root,
            )

            self.assertEqual(result, expected_path.resolve())

    def test_hugging_face_fallback_runs_after_llmfit_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            source_model = local_source_model("qwen2.5-coder-7b-instruct-q4-k-m", source="llmfit")

            with patch(
                "aistackd.models.acquisition.subprocess.run",
                side_effect=_fake_hf_download_subprocess_run,
            ):
                result = acquire_managed_model_artifact(
                    project_root,
                    source_model,
                    hugging_face_repo="unsloth/Qwen2.5-Coder-7B-Instruct-GGUF",
                    hugging_face_file="Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
                )

            self.assertEqual(result.source, "hugging_face")
            self.assertEqual(result.acquisition_method, "hugging_face_download")
            self.assertEqual(result.attempts[0].provider, "local")
            self.assertFalse(result.attempts[0].ok)
            self.assertEqual(result.attempts[1].provider, "llmfit")
            self.assertFalse(result.attempts[1].ok)
            self.assertEqual(result.attempts[2].provider, "hugging_face")
            self.assertTrue(result.attempts[2].ok)
            self.assertTrue(Path(result.artifact_path).exists())

    def test_import_managed_gguf_candidates_skips_duplicates_and_suffixes_hash_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            imports_root = Path(tmpdir) / "imports"
            first_path = _create_fake_gguf(imports_root, "GLM-4.7-Flash-Claude-4.5-Opus.Q4_K_M.gguf")
            second_path = _create_fake_gguf(
                imports_root,
                "GLM-4.7-Flash-Claude-4.5-Opus-v2.Q4_K_M.gguf",
                payload=b"GGUF\x00different-model\n",
            )
            duplicate_copy = _create_fake_gguf(
                imports_root / "nested",
                "GLM-4.7-Flash-Claude-4.5-Opus-copy.Q4_K_M.gguf",
                payload=first_path.read_bytes(),
            )
            same_name_duplicate = _create_fake_gguf(
                imports_root / "mirrored",
                "GLM-4.7-Flash-Claude-4.5-Opus.Q4_K_M.gguf",
                payload=first_path.read_bytes(),
            )

            first_report = import_managed_gguf_candidates(project_root, (first_path,), source_name="llmfit")
            duplicate_report = import_managed_gguf_candidates(
                project_root,
                (first_path, same_name_duplicate, duplicate_copy),
                source_name="llmfit",
            )
            collision_report = import_managed_gguf_candidates(
                project_root,
                (second_path,),
                source_name="llmfit",
            )

            self.assertEqual(first_report.imported_count, 1)
            self.assertEqual(duplicate_report.skipped_count, 2)
            self.assertEqual(duplicate_report.imported_count, 1)
            self.assertEqual(collision_report.imported_count, 1)
            self.assertEqual(collision_report.entries[0].action, "imported")
            self.assertEqual(
                collision_report.entries[0].model,
                "glm-4.7-flash-claude-4.5-opus-v2.q4-k-m",
            )

    def test_parse_hugging_face_url_extracts_repo_and_show_file_info(self) -> None:
        reference = parse_hugging_face_url(
            "https://huggingface.co/TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF"
            "?show_file_info=glm-4.7-flash-claude-4.5-opus.q4_k_m.gguf"
        )

        self.assertEqual(reference.repo, "TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF")
        self.assertEqual(reference.filename, "glm-4.7-flash-claude-4.5-opus.q4_k_m.gguf")


def _create_fake_gguf(root: Path, filename: str, *, payload: bytes = b"GGUF\x00test-model\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / filename
    artifact_path.write_bytes(payload)
    return artifact_path


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
