from __future__ import annotations

import pytest

from ai_stack.stack.manager import SetupManager


def test_normalize_hf_repo_id_accepts_repo_id() -> None:
    assert SetupManager.normalize_hf_repo_id("TheBloke/Llama-2-7B-GGUF") == "TheBloke/Llama-2-7B-GGUF"


def test_normalize_hf_repo_id_accepts_model_url() -> None:
    repo = SetupManager.normalize_hf_repo_id(
        "https://huggingface.co/TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF"
    )
    assert repo == "TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF"


def test_normalize_hf_repo_id_accepts_models_prefix_url() -> None:
    repo = SetupManager.normalize_hf_repo_id(
        "https://huggingface.co/models/TheBloke/Llama-2-7B-GGUF"
    )
    assert repo == "TheBloke/Llama-2-7B-GGUF"


def test_normalize_hf_repo_id_rejects_non_hf_host() -> None:
    with pytest.raises(ValueError, match="Unsupported host"):
        SetupManager.normalize_hf_repo_id("https://example.com/TheBloke/Llama-2-7B-GGUF")
