"""
ModelRegistry - local manifest of installed GGUF models and mmproj files.
- manifest.json is the local "what is installed" registry
- Do NOT fetch HuggingFace metadata here (that belongs to HF cache/client)

Manifest is designed to be:
- created on demand (ensure_manifest)
- updated after downloads (register_*)
- repairable if user drops files manually (scan_models_dir)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def _utc_now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _safe_stat_size(path: Path) -> Optional[int]:
    """Return file size in bytes, or None if missing/unreadable."""
    try:
        return path.stat().st_size
    except OSError:
        return None


class ModelRegistry:
    """
    Manages models/manifest.json (and optionally mmproj entries).

    This class should be "dumb storage":
    - load/save manifest
    - scan local directory
    - register/remove entries
    - resolve mmproj pairing
    """

    DEFAULT_MANIFEST: Dict[str, Any] = {
        "schema_version": 1,
        "updated_at": None,
        "models_dir": "models",
        "models": [],
        "mmproj_files": [],
    }

    def __init__(
        self,
        models_dir: Union[str, Path],
        manifest_path: Optional[Union[str, Path]] = None,
    ):
        self.models_dir = Path(models_dir)
        self.manifest_path = Path(manifest_path) if manifest_path else (self.models_dir / "manifest.json")

        # In-memory manifest dict (loaded lazily)
        self.manifest: Dict[str, Any] = {}

    # ---------------------------------------------------------------------
    # Public entrypoints
    # ---------------------------------------------------------------------

    def ensure_manifest(self) -> Dict[str, Any]:
        """
        Ensure manifest exists and is loaded into memory.

        - If missing: create default manifest and save it.
        - If present: load and validate schema_version.
        """
        if self.manifest:
            return self.manifest
    
        manifest = self.load_or_create_manifest()

        # Basic schema validation
        schema_version = manifest.get("schema_version")
        if schema_version != self.DEFAULT_MANIFEST["schema_version"]:
            raise ValueError(
                f"Unsupported manifest schema_version={schema_version}. "
                f"Expected {self.DEFAULT_MANIFEST['schema_version']}."
            )

        self.manifest = manifest
        return self.manifest

    def scan_models_dir(self) -> Dict[str, int]:
        """
        Repair-mode scan:
        - Add any .gguf files in models_dir that are not in manifest.
        - Distinguish mmproj files by name containing 'mmproj'.

        Does NOT call HuggingFace or guess repo_id.
        """
        self.ensure_manifest()

        added_models = 0
        added_mmproj = 0
        skipped = 0

        if not self.models_dir.exists():
            # If models_dir doesn't exist yet, create it and return.
            self.models_dir.mkdir(parents=True, exist_ok=True)
            return {"added_models": 0, "added_mmproj": 0, "skipped": 0}

        for path in sorted(self.models_dir.glob("*.gguf")):
            name = path.name
            is_mmproj = "mmproj" in name.lower()

            # Check if already in manifest
            if is_mmproj:
                if self._mmproj_entry_exists(name=name):
                    skipped += 1
                    continue
                self.register_mmproj(path=path, origin="local", for_models=None, save=False)
                added_mmproj += 1
            else:
                if self._model_entry_exists(name=name):
                    skipped += 1
                    continue
                self.register_model(path=path, origin="local", mmproj_path=None, repo=None, derived=None, save=False)
                added_models += 1

        if added_models or added_mmproj:
            self.save_manifest()

        return {"added_models": added_models, "added_mmproj": added_mmproj, "skipped": skipped}

    def register_model(
        self,
        path: Union[str, Path],
        origin: str,
        mmproj_path: Optional[Union[str, Path]] = None,
        repo: Optional[Dict[str, Optional[str]]] = None,
        derived: Optional[Dict[str, Any]] = None,
        save: bool = True,
    ) -> Dict[str, Any]:
        """
        Add or update a model entry.

        origin: "local" or "huggingface"
        repo: {"repo_id": str|None, "revision": str|None, "sha": str|None, "source_url": str|None}
        derived: {"family":..., "quant":..., "size":...} (optional)
        """
        self.ensure_manifest()

        path = Path(path)
        if not path.is_absolute():
            # Allow passing "models/foo.gguf" or "foo.gguf"
            candidate = self.models_dir / path
            path = candidate if candidate.exists() else path

        name = path.name
        rel_path = self._to_rel_models_path(path)

        entry = self._find_model_entry(name=name)
        if entry is None:
            entry = {
                "id": self._make_model_id(name),
                "name": name,
                "path": rel_path,
                "origin": origin,
                "installed_at": _utc_now_iso(),
                "size_bytes": _safe_stat_size(path),
                "repo": {
                    "repo_id": None,
                    "revision": None,
                    "sha": None,
                    "source_url": None,
                },
                "pairing": {
                    "requires_mmproj": False,
                    "mmproj_path": None,
                },
                "derived": {},
                "runtime_hints": {
                    "context_size": None,
                    "chat_template": None,
                },
            }
            self.manifest["models"].append(entry)
        else:
            # Update mutable fields
            entry["path"] = rel_path
            entry["origin"] = origin
            entry["size_bytes"] = _safe_stat_size(path)
            entry["installed_at"] = entry.get("installed_at") or _utc_now_iso()

        # Repo provenance (optional)
        if repo:
            entry["repo"].update({k: repo.get(k) for k in entry["repo"].keys()})

        # Pairing
        if mmproj_path:
            mp = Path(mmproj_path)
            entry["pairing"]["requires_mmproj"] = True
            entry["pairing"]["mmproj_path"] = self._to_rel_models_path(mp)
        else:
            # leave as-is; do not wipe existing pairing unless you explicitly want that
            pass

        # Derived (optional)
        if derived:
            entry["derived"].update(derived)

        if save:
            self.save_manifest()

        return entry

    def register_mmproj(
        self,
        path: Union[str, Path],
        origin: str,
        for_models: Optional[List[str]] = None,
        repo: Optional[Dict[str, Optional[str]]] = None,
        save: bool = True,
    ) -> Dict[str, Any]:
        """
        Add or update an mmproj entry.

        for_models: list of model filenames this mmproj applies to (optional)
        repo: {"repo_id": str|None, "revision": str|None, "sha": str|None, "source_url": str|None}
        """
        self.ensure_manifest()

        path = Path(path)
        name = path.name
        rel_path = self._to_rel_models_path(path)

        entry = self._find_mmproj_entry(name=name)
        if entry is None:
            entry = {
                "name": name,
                "path": rel_path,
                "origin": origin,
                "installed_at": _utc_now_iso(),
                "size_bytes": _safe_stat_size(path),
                "repo": {
                    "repo_id": None,
                    "revision": None,
                    "sha": None,
                    "source_url": None,
                },
                "for_models": [],
            }
            self.manifest["mmproj_files"].append(entry)
        else:
            entry["path"] = rel_path
            entry["origin"] = origin
            entry["size_bytes"] = _safe_stat_size(path)

        if repo:
            entry["repo"].update({k: repo.get(k) for k in entry["repo"].keys()})

        if for_models:
            # merge, keep unique
            merged = set(entry.get("for_models", []))
            merged.update(for_models)
            entry["for_models"] = sorted(merged)

        if save:
            self.save_manifest()

        return entry

    def get_mmproj_for_model(self, model_path: Union[str, Path]) -> Optional[Path]:
        """
        Resolve mmproj for a given model using manifest only (Phase A).

        Lookup order:
        1) model entry pairing.mmproj_path (if exists and file exists)
        2) mmproj_files entries that list this model filename in for_models
        """
        self.ensure_manifest()

        model_path = Path(model_path)
        model_name = model_path.name  # works for full paths or "foo.gguf"

        # 1) direct pairing on model entry
        model_entry = self._find_model_entry(name=model_name)
        if model_entry:
            mmproj_rel = (model_entry.get("pairing") or {}).get("mmproj_path")
            if mmproj_rel:
                mmproj_abs = self._to_abs_models_path(mmproj_rel)
                if mmproj_abs.exists():
                    return mmproj_abs

        # 2) check mmproj_files for_models lists
        for mp in self.manifest.get("mmproj_files", []):
            if model_name in (mp.get("for_models") or []):
                mmproj_abs = self._to_abs_models_path(mp["path"])
                if mmproj_abs.exists():
                    return mmproj_abs

        return None

    def remove_model(self, identifier: str, delete_file: bool = False) -> bool:
        """
        Remove a model entry by:
        - id (preferred) or
        - exact filename

        If delete_file=True, also deletes the local .gguf file (careful).
        """
        self.ensure_manifest()

        models = self.manifest.get("models", [])
        idx = self._find_model_index(identifier)
        if idx is None:
            return False

        entry = models.pop(idx)

        if delete_file:
            abs_path = self._to_abs_models_path(entry["path"])
            try:
                if abs_path.exists():
                    abs_path.unlink()
            except OSError:
                # If delete fails, we still removed from manifest.
                pass

        self.save_manifest()
        return True

    def prune_orphan_mmproj(self, remove_missing_only: bool = True) -> Dict[str, int]:
        """
        Remove mmproj entries that aren't referenced by any model.

        remove_missing_only=True means:
        - only remove if unreferenced AND file is missing on disk
        """
        self.ensure_manifest()

        referenced: set[str] = set()
        for m in self.manifest.get("models", []):
            mp = (m.get("pairing") or {}).get("mmproj_path")
            if mp:
                referenced.add(mp)

        kept: List[Dict[str, Any]] = []
        removed = 0

        for mp_entry in self.manifest.get("mmproj_files", []):
            path_rel = mp_entry.get("path")
            abs_path = self._to_abs_models_path(path_rel) if path_rel else None

            is_referenced = path_rel in referenced
            exists = abs_path.exists() if abs_path else False

            if is_referenced:
                kept.append(mp_entry)
                continue

            if remove_missing_only and exists:
                kept.append(mp_entry)
                continue

            # orphan -> remove
            removed += 1

        self.manifest["mmproj_files"] = kept
        if removed:
            self.save_manifest()

        return {"removed": removed, "kept": len(kept)}

    # ---------------------------------------------------------------------
    # IO helpers
    # ---------------------------------------------------------------------

    def load_or_create_manifest(self) -> Dict[str, Any]:
        """Load manifest from disk, or create a default one."""
        self.models_dir.mkdir(parents=True, exist_ok=True)

        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Ensure required top-level keys exist
                for k, v in self.DEFAULT_MANIFEST.items():
                    data.setdefault(k, v if not isinstance(v, list) else list(v))
                return data
            except (OSError, json.JSONDecodeError):
                # If corrupted, fall back to default (you could also raise)
                pass

        data = {
            "schema_version": self.DEFAULT_MANIFEST["schema_version"],
            "updated_at": _utc_now_iso(),
            "models_dir": self.DEFAULT_MANIFEST["models_dir"],
            "models": [],
            "mmproj_files": [],
        }
        self._write_manifest(data)
        return data

    def save_manifest(self) -> None:
        """Persist in-memory manifest to disk."""
        if not self.manifest:
            # If user calls save before ensure, do the safe thing.
            self.ensure_manifest()

        self.manifest["updated_at"] = _utc_now_iso()
        self._write_manifest(self.manifest)

    def _write_manifest(self, data: Dict[str, Any]) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _to_rel_models_path(self, path: Path) -> str:
        """
        Convert an absolute or relative path to a stable 'models/...' string
        when possible.
        """
        # If path is already under models_dir, store relative to repo root as "models/..."
        try:
            abs_models = self.models_dir.resolve()
            abs_path = path.resolve()
            rel = abs_path.relative_to(abs_models)
            return str(Path(self.models_dir.name) / rel)  # "models/foo.gguf"
        except Exception:
            # Fallback: store as given (still a string)
            return str(path)

    def _to_abs_models_path(self, rel_or_path: str) -> Path:
        """Convert a manifest path string to an absolute filesystem path."""
        p = Path(rel_or_path)
        if p.is_absolute():
            return p
        # If manifest stores "models/foo.gguf", strip leading "models/"
        if p.parts and p.parts[0] == self.models_dir.name:
            p = Path(*p.parts[1:])
        return (self.models_dir / p).resolve()

    def _make_model_id(self, filename: str) -> str:
        """Stable-ish id derived from filename."""
        return filename.lower().replace(" ", "-")

    def _find_model_entry(self, name: str) -> Optional[Dict[str, Any]]:
        for m in self.manifest.get("models", []):
            if m.get("name") == name:
                return m
        return None

    def _model_entry_exists(self, name: str) -> bool:
        return self._find_model_entry(name) is not None

    def _find_mmproj_entry(self, name: str) -> Optional[Dict[str, Any]]:
        for mp in self.manifest.get("mmproj_files", []):
            if mp.get("name") == name:
                return mp
        return None

    def _mmproj_entry_exists(self, name: str) -> bool:
        return self._find_mmproj_entry(name) is not None

    def _find_model_index(self, identifier: str) -> Optional[int]:
        """
        Find model index by id or name.
        """
        identifier = identifier.strip()
        for i, m in enumerate(self.manifest.get("models", [])):
            if m.get("id") == identifier or m.get("name") == identifier:
                return i
        return None
