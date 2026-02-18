from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional

from ai_stack.huggingface.client import RepoFile, RepoSnapshot

DEFAULT_QUANT_RANKING: List[str] = [
    "IQ4_NL",
    "Q4_K_M",
    "Q5_K_M",
    "Q8_0",
    "Q4_0",
    "Q3_K_M",
    "Q2_K",
]


@dataclass(frozen=True)
class ResolvedDownload:
    repo_id: str
    revision: str
    sha: Optional[str]
    model_file: RepoFile
    mmproj_file: Optional[RepoFile]


def parse_quant_from_filename(path: str) -> Optional[str]:
    """
    Extract quant token from GGUF filename, e.g. Q4_K_M, IQ4_NL, Q8_0.
    """
    upper = path.upper()
    patterns = [
        r"(IQ\d+_[A-Z0-9_]+)",
        r"(Q\d+_[A-Z0-9_]+)",
        r"(Q\d+_\d+)",
        r"(Q\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, upper)
        if match:
            return match.group(1)
    return None


def _rank_for_quant(quant: Optional[str], ranking: List[str]) -> int:
    if not quant:
        return len(ranking) + 100
    quant_u = quant.upper()
    try:
        return ranking.index(quant_u)
    except ValueError:
        return len(ranking) + 10


def pick_gguf_file(snapshot: RepoSnapshot, preferred_quants: List[str]) -> RepoFile:
    ggufs = snapshot.gguf_files
    if not ggufs:
        raise ValueError(f"No GGUF files found in repo {snapshot.repo_id}")

    preferred = [q.upper() for q in preferred_quants if q]
    ranked = [q.upper() for q in DEFAULT_QUANT_RANKING]

    quant_by_path = {f.path: parse_quant_from_filename(f.path) for f in ggufs}

    # Try explicit preference first (CLI / caller override)
    for preferred_quant in preferred:
        for f in ggufs:
            parsed = (quant_by_path.get(f.path) or "").upper()
            if parsed == preferred_quant or preferred_quant in f.path.upper():
                return f

    # Fallback to ranked quant list
    sorted_ggufs = sorted(
        ggufs,
        key=lambda f: (
            _rank_for_quant(quant_by_path.get(f.path), ranked),
            f.path.lower(),
        ),
    )
    if sorted_ggufs:
        return sorted_ggufs[0]

    # Final fallback: any Q4, else first
    for f in ggufs:
        if "Q4" in f.path.upper():
            return f
    return ggufs[0]


def pick_mmproj_file(snapshot: RepoSnapshot) -> Optional[RepoFile]:
    mmps = snapshot.mmproj_files
    return mmps[0] if mmps else None


def resolve_download(snapshot: RepoSnapshot, preferred_quants: List[str]) -> ResolvedDownload:
    model_file = pick_gguf_file(snapshot, preferred_quants)
    mmproj_file = pick_mmproj_file(snapshot)
    return ResolvedDownload(
        repo_id=snapshot.repo_id,
        revision=snapshot.revision,
        sha=snapshot.sha,
        model_file=model_file,
        mmproj_file=mmproj_file,
    )
