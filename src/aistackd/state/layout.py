"""Project layout inspection helpers for the scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aistackd.frontends.catalog import SUPPORTED_FRONTENDS
from aistackd.models.sources import BACKEND_ACQUISITION_POLICY, MODEL_SOURCE_POLICY, PRIMARY_BACKEND
from aistackd.runtime.modes import all_runtime_modes
from aistackd.skills.catalog import BASELINE_SKILLS, SHARED_SKILLS_DIRECTORY_NAME, SHARED_TOOLS_DIRECTORY_NAME
from aistackd.state.host import HostStatePaths
from aistackd.state.profiles import ProfileStatePaths
from aistackd.state.sync import SyncStatePaths

COMMAND_GROUPS = ("host", "client", "profiles", "models", "sync", "doctor")


@dataclass(frozen=True)
class PathCheck:
    """Presence check for a scaffold path."""

    label: str
    path: str
    exists: bool


@dataclass(frozen=True)
class ProjectLayout:
    """Structured summary of the current scaffold layout."""

    project_root: str
    package_root: str
    runtime_backend: str
    backend_policy: str
    model_source_policy: str
    command_groups: tuple[str, ...]
    runtime_modes: tuple[str, ...]
    frontends: tuple[str, ...]
    planned_baseline_skills: tuple[str, ...]
    scaffold_paths: tuple[PathCheck, ...]
    reserved_paths: tuple[PathCheck, ...]

    @classmethod
    def discover(cls, project_root: Path) -> "ProjectLayout":
        """Inspect the repository scaffold rooted at ``project_root``."""
        root = project_root.resolve()
        package_root = root / "src" / "aistackd"
        profile_paths = ProfileStatePaths.from_project_root(root)
        host_paths = HostStatePaths.from_project_root(root)
        sync_paths = SyncStatePaths.from_project_root(root)

        scaffold_paths = (
            PathCheck("package_root", str(package_root), package_root.exists()),
            PathCheck("cli_commands", str(package_root / "cli" / "commands"), (package_root / "cli" / "commands").exists()),
            PathCheck("runtime_package", str(package_root / "runtime"), (package_root / "runtime").exists()),
            PathCheck("control_plane_package", str(package_root / "control_plane"), (package_root / "control_plane").exists()),
            PathCheck("frontends_package", str(package_root / "frontends"), (package_root / "frontends").exists()),
            PathCheck("models_package", str(package_root / "models"), (package_root / "models").exists()),
            PathCheck("skills_package", str(package_root / "skills"), (package_root / "skills").exists()),
            PathCheck("state_package", str(package_root / "state"), (package_root / "state").exists()),
            PathCheck("tests", str(root / "tests"), (root / "tests").exists()),
            PathCheck("ci_workflow", str(root / ".github" / "workflows" / "ci.yml"), (root / ".github" / "workflows" / "ci.yml").exists()),
            PathCheck("shared_skills", str(root / SHARED_SKILLS_DIRECTORY_NAME), (root / SHARED_SKILLS_DIRECTORY_NAME).exists()),
            PathCheck("shared_tools", str(root / SHARED_TOOLS_DIRECTORY_NAME), (root / SHARED_TOOLS_DIRECTORY_NAME).exists()),
        )

        reserved_paths = (
            PathCheck("runtime_state_root", str(profile_paths.runtime_state_root), profile_paths.runtime_state_root.exists()),
            PathCheck("profile_store", str(profile_paths.profiles_dir), profile_paths.profiles_dir.exists()),
            PathCheck("active_profile_file", str(profile_paths.active_profile_path), profile_paths.active_profile_path.exists()),
            PathCheck("host_state_dir", str(host_paths.host_dir), host_paths.host_dir.exists()),
            PathCheck("host_runtime_file", str(host_paths.runtime_state_path), host_paths.runtime_state_path.exists()),
            PathCheck("installed_models_file", str(host_paths.installed_models_path), host_paths.installed_models_path.exists()),
            PathCheck("sync_state_dir", str(sync_paths.sync_dir), sync_paths.sync_dir.exists()),
            PathCheck("ownership_manifest_file", str(sync_paths.ownership_manifest_path), sync_paths.ownership_manifest_path.exists()),
        )

        return cls(
            project_root=str(root),
            package_root=str(package_root),
            runtime_backend=PRIMARY_BACKEND,
            backend_policy=BACKEND_ACQUISITION_POLICY,
            model_source_policy=MODEL_SOURCE_POLICY,
            command_groups=COMMAND_GROUPS,
            runtime_modes=all_runtime_modes(),
            frontends=SUPPORTED_FRONTENDS,
            planned_baseline_skills=BASELINE_SKILLS,
            scaffold_paths=scaffold_paths,
            reserved_paths=reserved_paths,
        )

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the layout."""
        return {
            "project_root": self.project_root,
            "package_root": self.package_root,
            "runtime_backend": self.runtime_backend,
            "backend_policy": self.backend_policy,
            "model_source_policy": self.model_source_policy,
            "command_groups": list(self.command_groups),
            "runtime_modes": list(self.runtime_modes),
            "frontends": list(self.frontends),
            "planned_baseline_skills": list(self.planned_baseline_skills),
            "scaffold_paths": [check.__dict__ for check in self.scaffold_paths],
            "reserved_paths": [check.__dict__ for check in self.reserved_paths],
        }

    def format_text(self) -> str:
        """Return a readable multi-line scaffold report."""
        lines = [
            "aistackd scaffold report",
            f"project_root: {self.project_root}",
            f"package_root: {self.package_root}",
            f"runtime_backend: {self.runtime_backend}",
            f"backend_policy: {self.backend_policy}",
            f"model_source_policy: {self.model_source_policy}",
            f"command_groups: {', '.join(self.command_groups)}",
            f"runtime_modes: {', '.join(self.runtime_modes)}",
            f"frontends: {', '.join(self.frontends)}",
            f"planned_baseline_skills: {', '.join(self.planned_baseline_skills)}",
            "scaffold_paths:",
        ]

        for check in self.scaffold_paths:
            status = "present" if check.exists else "missing"
            lines.append(f"  {check.label}: {status} ({check.path})")

        lines.append("reserved_paths:")
        for check in self.reserved_paths:
            status = "created" if check.exists else "not_created"
            lines.append(f"  {check.label}: {status} ({check.path})")

        return "\n".join(lines)
