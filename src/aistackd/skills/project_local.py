"""Project-local skill workflow conventions."""

from __future__ import annotations

from pathlib import Path

PROJECT_LOCAL_SHARED_SKILLS_ROOT = Path(".agents") / "skills"
PROJECT_LOCAL_OPENHANDS_SKILLS_ROOT = Path(".openhands") / "skills"
PROJECT_LOCAL_SKILL_PROVENANCE_FILE_NAME = "aistackd-skill-provenance.json"


def project_local_skill_roots(frontend: str) -> tuple[Path, ...]:
    """Return the recommended unmanaged project-local skill roots for a frontend."""
    if frontend in {"codex", "opencode"}:
        return (PROJECT_LOCAL_SHARED_SKILLS_ROOT,)
    if frontend == "openhands":
        return (PROJECT_LOCAL_OPENHANDS_SKILLS_ROOT,)
    raise ValueError(f"unsupported frontend '{frontend}'")


def project_local_skill_note(frontend: str) -> str:
    """Return a user-facing note describing the project-local skill workflow."""
    roots = ", ".join(str(path) for path in project_local_skill_roots(frontend))
    return (
        f"project-local external skills should prefer {roots}; sync preserves unmanaged installs, "
        f"and adopted external skills may record provenance in {PROJECT_LOCAL_SKILL_PROVENANCE_FILE_NAME}"
    )
