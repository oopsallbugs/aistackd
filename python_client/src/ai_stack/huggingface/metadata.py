from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ai_stack.huggingface.client import RepoFile
from ai_stack.huggingface.resolver import parse_quant_from_filename


def _bytes_to_human(size_bytes: Optional[int]) -> Optional[str]:
    if not size_bytes or size_bytes <= 0:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit_index = 0
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"


def extract_parameter_scale(*texts: str) -> Optional[str]:
    for text in texts:
        if not text:
            continue
        # Matches 7B, 13b, 0.5B, 70B, etc.
        match = re.search(r"(\d+(?:\.\d+)?)\s*B\b", text, re.IGNORECASE)
        if match:
            return f"{match.group(1)}B"
    return None


def extract_family(repo_id: str, filename: str) -> str:
    repo_name = (repo_id.split("/")[-1] if repo_id else "").strip()
    base = repo_name or filename
    base = re.sub(r"[-_]?GGUF$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"[-_](Q\d+|IQ\d+).*$", "", base, flags=re.IGNORECASE)
    return base


def derive_model_metadata(repo_id: str, model_file: RepoFile) -> Dict[str, Any]:
    parameter_scale = extract_parameter_scale(model_file.path, repo_id)
    quant = parse_quant_from_filename(model_file.path)
    size_human = _bytes_to_human(model_file.size)

    return {
        "family": extract_family(repo_id=repo_id, filename=model_file.path),
        "quant": quant,
        "model_size": size_human,
        "parameter_scale": parameter_scale,
    }
