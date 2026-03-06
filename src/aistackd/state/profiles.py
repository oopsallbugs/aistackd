"""Profile state paths, contracts, and storage."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

RUNTIME_STATE_DIRECTORY_NAME = ".aistackd"
PROFILES_DIRECTORY_NAME = "profiles"
ACTIVE_PROFILE_FILE_NAME = "active_profile"
PROFILE_FILE_SUFFIX = ".json"
CURRENT_PROFILE_SCHEMA_VERSION = "v1alpha1"
ALLOWED_PROFILE_ROLE_HINTS = ("host", "client", "hybrid", "remote_host", "local")

_PROFILE_NAME_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_ENVIRONMENT_VARIABLE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_REQUIRED_PROFILE_FIELDS = ("schema_version", "name", "base_url", "api_key_env")
_OPTIONAL_PROFILE_FIELDS = ("role_hint", "description")
_KNOWN_PROFILE_FIELDS = set(_REQUIRED_PROFILE_FIELDS + _OPTIONAL_PROFILE_FIELDS)


class ProfileStoreError(RuntimeError):
    """Base exception for profile storage operations."""


class ProfileNotFoundError(ProfileStoreError):
    """Raised when a requested profile does not exist."""


class ProfileValidationError(ProfileStoreError):
    """Raised when a profile definition is invalid."""

    def __init__(self, messages: tuple[str, ...] | list[str]) -> None:
        self.messages = tuple(messages)
        super().__init__("; ".join(self.messages))


@dataclass(frozen=True)
class ProfileValidationResult:
    """Validation result for a stored profile."""

    name: str
    ok: bool
    definition_errors: tuple[str, ...] = ()
    readiness_errors: tuple[str, ...] = ()

    @property
    def messages(self) -> tuple[str, ...]:
        """Return all error messages in display order."""
        return self.definition_errors + self.readiness_errors

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "name": self.name,
            "ok": self.ok,
            "definition_errors": list(self.definition_errors),
            "readiness_errors": list(self.readiness_errors),
        }


@dataclass(frozen=True)
class Profile:
    """Profile contract for a named backend target."""

    name: str
    base_url: str
    api_key_env: str
    role_hint: str | None = None
    description: str | None = None
    schema_version: str = CURRENT_PROFILE_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Profile":
        """Decode a profile from a JSON object."""
        missing = [field_name for field_name in _REQUIRED_PROFILE_FIELDS if field_name not in payload]
        if missing:
            raise ProfileValidationError([f"missing required field: {field_name}" for field_name in missing])

        unknown = sorted(set(payload) - _KNOWN_PROFILE_FIELDS)
        if unknown:
            raise ProfileValidationError([f"unexpected field: {field_name}" for field_name in unknown])

        return cls(
            schema_version=_require_string(payload, "schema_version"),
            name=_require_string(payload, "name"),
            base_url=_require_string(payload, "base_url"),
            api_key_env=_require_string(payload, "api_key_env"),
            role_hint=_optional_string(payload, "role_hint"),
            description=_optional_string(payload, "description"),
        ).normalized()

    def normalized(self) -> "Profile":
        """Return a copy with normalized whitespace and URL formatting."""
        normalized_base_url = self.base_url.strip().rstrip("/")
        if not normalized_base_url:
            normalized_base_url = self.base_url.strip()

        normalized_role_hint = self.role_hint.strip() if isinstance(self.role_hint, str) else None
        normalized_description = self.description.strip() if isinstance(self.description, str) else None

        return Profile(
            schema_version=self.schema_version.strip(),
            name=self.name.strip(),
            base_url=normalized_base_url,
            api_key_env=self.api_key_env.strip(),
            role_hint=normalized_role_hint or None,
            description=normalized_description or None,
        )

    def definition_errors(self) -> tuple[str, ...]:
        """Return structural validation errors for this profile."""
        messages: list[str] = []

        if self.schema_version != CURRENT_PROFILE_SCHEMA_VERSION:
            messages.append(
                f"unsupported schema_version '{self.schema_version}'; expected '{CURRENT_PROFILE_SCHEMA_VERSION}'"
            )

        if not _PROFILE_NAME_RE.fullmatch(self.name):
            messages.append(
                "name must use lowercase letters, numbers, hyphens, or underscores"
            )

        parsed_url = urlparse(self.base_url)
        if not self.base_url:
            messages.append("base_url is required")
        elif parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            messages.append("base_url must be a valid http or https URL")
        elif parsed_url.query or parsed_url.fragment:
            messages.append("base_url must not include query or fragment components")

        if not _ENVIRONMENT_VARIABLE_RE.fullmatch(self.api_key_env):
            messages.append("api_key_env must be a valid uppercase environment variable name")

        if self.role_hint is not None and self.role_hint not in ALLOWED_PROFILE_ROLE_HINTS:
            messages.append(
                f"role_hint must be one of: {', '.join(ALLOWED_PROFILE_ROLE_HINTS)}"
            )

        return tuple(messages)

    def readiness_errors(self) -> tuple[str, ...]:
        """Return environment readiness errors for this profile."""
        if not os.getenv(self.api_key_env, "").strip():
            return (f"api key environment variable '{self.api_key_env}' is not set or empty",)
        return ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the profile."""
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
        }
        if self.role_hint is not None:
            payload["role_hint"] = self.role_hint
        if self.description is not None:
            payload["description"] = self.description
        return payload


@dataclass(frozen=True)
class ProfileStatePaths:
    """Canonical profile-related state paths."""

    runtime_state_root: Path
    profiles_dir: Path
    active_profile_path: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> "ProfileStatePaths":
        """Derive profile state paths from a project root."""
        root = project_root.resolve()
        runtime_state_root = root / RUNTIME_STATE_DIRECTORY_NAME
        return cls(
            runtime_state_root=runtime_state_root,
            profiles_dir=runtime_state_root / PROFILES_DIRECTORY_NAME,
            active_profile_path=runtime_state_root / ACTIVE_PROFILE_FILE_NAME,
        )

    def profile_path(self, profile_name: str) -> Path:
        """Return the file path for a named profile."""
        return self.profiles_dir / f"{profile_name}{PROFILE_FILE_SUFFIX}"


class ProfileStore:
    """JSON-backed storage for named profiles and the active pointer."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.paths = ProfileStatePaths.from_project_root(self.project_root)

    def ensure_storage(self) -> None:
        """Create the profile storage directories if they do not exist."""
        self.paths.profiles_dir.mkdir(parents=True, exist_ok=True)

    def available_profile_names(self) -> tuple[str, ...]:
        """Return profile names derived from stored JSON files."""
        if not self.paths.profiles_dir.exists():
            return ()

        names = [
            path.stem
            for path in sorted(self.paths.profiles_dir.glob(f"*{PROFILE_FILE_SUFFIX}"))
            if path.is_file()
        ]
        return tuple(names)

    def list_profiles(self) -> tuple[Profile, ...]:
        """Load all configured profiles in sorted order."""
        return tuple(self.load_profile(profile_name) for profile_name in self.available_profile_names())

    def load_profile(self, profile_name: str) -> Profile:
        """Load a profile by name."""
        _validate_profile_name(profile_name)
        path = self.paths.profile_path(profile_name)
        if not path.exists():
            raise ProfileNotFoundError(f"profile '{profile_name}' does not exist")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProfileValidationError([f"profile '{profile_name}' contains invalid JSON: {exc.msg}"]) from exc

        if not isinstance(payload, dict):
            raise ProfileValidationError([f"profile '{profile_name}' must be a JSON object"])

        profile = Profile.from_dict(payload)
        if profile.name != profile_name:
            raise ProfileValidationError(
                [f"profile file '{path.name}' does not match profile name '{profile.name}'"]
            )

        definition_errors = profile.definition_errors()
        if definition_errors:
            raise ProfileValidationError(list(definition_errors))

        return profile

    def save_profile(self, profile: Profile) -> bool:
        """Save a profile definition, returning ``True`` when newly created."""
        normalized = profile.normalized()
        definition_errors = normalized.definition_errors()
        if definition_errors:
            raise ProfileValidationError(list(definition_errors))

        self.ensure_storage()
        profile_path = self.paths.profile_path(normalized.name)
        created = not profile_path.exists()
        _write_json_atomic(profile_path, normalized.to_dict())
        return created

    def get_active_profile_name(self) -> str | None:
        """Return the active profile name, if configured."""
        if not self.paths.active_profile_path.exists():
            return None

        value = self.paths.active_profile_path.read_text(encoding="utf-8").strip()
        return value or None

    def get_active_profile(self) -> Profile | None:
        """Return the active profile object, if configured."""
        active_profile_name = self.get_active_profile_name()
        if active_profile_name is None:
            return None
        return self.load_profile(active_profile_name)

    def activate_profile(self, profile_name: str) -> Profile:
        """Set the active profile pointer after verifying the profile exists."""
        profile = self.load_profile(profile_name)
        self.paths.runtime_state_root.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(self.paths.active_profile_path, f"{profile.name}\n")
        return profile

    def validate_profile(self, profile_name: str) -> ProfileValidationResult:
        """Validate a single profile by name."""
        try:
            profile = self.load_profile(profile_name)
        except ProfileStoreError as exc:
            return ProfileValidationResult(
                name=profile_name,
                ok=False,
                definition_errors=(str(exc),),
            )

        readiness_errors = profile.readiness_errors()
        return ProfileValidationResult(
            name=profile.name,
            ok=not readiness_errors,
            readiness_errors=readiness_errors,
        )

    def validate_profiles(self) -> tuple[ProfileValidationResult, ...]:
        """Validate all stored profiles."""
        return tuple(self.validate_profile(profile_name) for profile_name in self.available_profile_names())


def _require_string(payload: dict[str, object], field_name: str) -> str:
    """Return a required string field or raise a validation error."""
    value = payload[field_name]
    if not isinstance(value, str):
        raise ProfileValidationError([f"field '{field_name}' must be a string"])
    return value


def _optional_string(payload: dict[str, object], field_name: str) -> str | None:
    """Return an optional string field or raise a validation error."""
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfileValidationError([f"field '{field_name}' must be a string when provided"])
    return value


def _validate_profile_name(profile_name: str) -> None:
    """Validate a profile name before using it in a path."""
    if not _PROFILE_NAME_RE.fullmatch(profile_name):
        raise ProfileValidationError(
            ["profile name must use lowercase letters, numbers, hyphens, or underscores"]
        )


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Write JSON data atomically."""
    _write_text_atomic(path, json.dumps(payload, indent=2) + "\n")


def _write_text_atomic(path: Path, contents: str) -> None:
    """Write text atomically to avoid partial state updates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(contents)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)
