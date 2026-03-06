"""Checkpoint schema, persistence, and resume helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional

from bootstrap.contracts import (
    BOOTSTRAP_CHECKPOINT_SCHEMA,
    BOOTSTRAP_PLAN_ID,
    STAGE_IDS,
)
from bootstrap.io_utils import atomic_write_json, atomic_write_text, sha256_for_mapping, utc_now_iso
from bootstrap.paths import checkpoint_path, current_run_path


@dataclass(frozen=True)
class StageFailure:
    code: str
    message: str
    retryable: bool


def _default_stage_payload(stage_id: str) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "status": "pending",
        "attempt_count": 0,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "input_hash": None,
        "output": {},
        "error_code": None,
        "error_message": None,
        "retryable": False,
    }


def build_checkpoint(
    *,
    run_id: str,
    inputs: dict[str, Any],
    environment: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema": BOOTSTRAP_CHECKPOINT_SCHEMA,
        "schema_version": 1,
        "run_id": run_id,
        "plan_id": BOOTSTRAP_PLAN_ID,
        "created_at": now,
        "updated_at": now,
        "run_status": "running",
        "current_stage": None,
        "last_completed_stage": None,
        "inputs_fingerprint": sha256_for_mapping(inputs),
        "inputs": inputs,
        "environment": environment,
        "artifacts": {},
        "stages": {stage_id: _default_stage_payload(stage_id) for stage_id in STAGE_IDS},
    }


def load_checkpoint(path: Path) -> Optional[dict[str, Any]]:
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def validate_checkpoint_schema(payload: dict[str, Any]) -> bool:
    required = (
        "schema",
        "schema_version",
        "run_id",
        "plan_id",
        "run_status",
        "inputs_fingerprint",
        "inputs",
        "environment",
        "artifacts",
        "stages",
    )
    for key in required:
        if key not in payload:
            return False
    if payload["schema"] != BOOTSTRAP_CHECKPOINT_SCHEMA:
        return False
    if payload["schema_version"] != 1:
        return False
    if payload["plan_id"] != BOOTSTRAP_PLAN_ID:
        return False
    if not isinstance(payload.get("stages"), dict):
        return False
    for stage_id in STAGE_IDS:
        if stage_id not in payload["stages"]:
            return False
    return True


def write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = utc_now_iso()
    atomic_write_json(path, payload)


def write_current_run(project_root: Path, run_id: str) -> None:
    path = current_run_path(project_root)
    atomic_write_text(path, f"{run_id}\n")


def _duration_ms(started_at: Optional[str]) -> Optional[int]:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    elapsed = datetime.now(timezone.utc) - started
    return int(elapsed.total_seconds() * 1000)


def mark_stage_started(payload: dict[str, Any], stage_id: str, *, input_hash: Optional[str]) -> int:
    stage = payload["stages"][stage_id]
    stage["status"] = "running"
    stage["attempt_count"] = int(stage.get("attempt_count", 0)) + 1
    stage["started_at"] = utc_now_iso()
    stage["finished_at"] = None
    stage["duration_ms"] = None
    stage["input_hash"] = input_hash
    stage["error_code"] = None
    stage["error_message"] = None
    payload["run_status"] = "running"
    payload["current_stage"] = stage_id
    return int(stage["attempt_count"])


def mark_stage_completed(payload: dict[str, Any], stage_id: str, *, output: dict[str, Any]) -> Optional[int]:
    stage = payload["stages"][stage_id]
    stage["status"] = "completed"
    stage["finished_at"] = utc_now_iso()
    stage["duration_ms"] = _duration_ms(stage.get("started_at"))
    stage["output"] = output
    stage["retryable"] = False
    payload["current_stage"] = None
    payload["last_completed_stage"] = stage_id
    if is_run_complete(payload):
        payload["run_status"] = "completed"
    return stage["duration_ms"]


def mark_stage_failed(payload: dict[str, Any], stage_id: str, failure: StageFailure) -> Optional[int]:
    stage = payload["stages"][stage_id]
    stage["status"] = "failed"
    stage["finished_at"] = utc_now_iso()
    stage["duration_ms"] = _duration_ms(stage.get("started_at"))
    stage["error_code"] = failure.code
    stage["error_message"] = failure.message
    stage["retryable"] = bool(failure.retryable)
    payload["run_status"] = "failed"
    payload["current_stage"] = stage_id
    return stage["duration_ms"]


def mark_stage_skipped(payload: dict[str, Any], stage_id: str, *, reason: str) -> Optional[int]:
    stage = payload["stages"][stage_id]
    stage["status"] = "skipped"
    stage["finished_at"] = utc_now_iso()
    stage["duration_ms"] = _duration_ms(stage.get("started_at"))
    stage["output"] = {"reason": reason}
    stage["retryable"] = False
    payload["current_stage"] = None
    if is_run_complete(payload):
        payload["run_status"] = "completed"
    return stage["duration_ms"]


def is_run_complete(payload: dict[str, Any]) -> bool:
    for stage_id in STAGE_IDS:
        status = payload["stages"][stage_id].get("status")
        if status not in {"completed", "skipped"}:
            return False
    return True


def update_artifacts_append_only(payload: dict[str, Any], updates: dict[str, Any]) -> None:
    artifacts = payload["artifacts"]
    for key, value in updates.items():
        if key in artifacts and artifacts[key] != value:
            raise RuntimeError(
                "Artifact '{}' already exists with different value in run '{}'".format(
                    key,
                    payload.get("run_id"),
                )
            )
        artifacts[key] = value


def assert_fingerprint_matches(payload: dict[str, Any], inputs: dict[str, Any]) -> None:
    expected = str(payload.get("inputs_fingerprint", ""))
    actual = sha256_for_mapping(inputs)
    if expected != actual:
        raise RuntimeError(
            "Resume blocked: invocation inputs do not match checkpoint fingerprint. "
            "Use the same arguments or start a new run."
        )


def next_stage_for_resume(payload: dict[str, Any]) -> Optional[str]:
    for stage_id in STAGE_IDS:
        stage = payload["stages"][stage_id]
        status = stage.get("status")
        if status in {"pending", "running"}:
            return stage_id
        if status == "failed" and bool(stage.get("retryable", False)):
            return stage_id
        if status == "failed" and not bool(stage.get("retryable", False)):
            raise RuntimeError(
                "Run is blocked on non-retryable failed stage '{}': {}".format(
                    stage_id,
                    stage.get("error_code") or "unknown_error",
                )
            )
    return None


def initialize_or_load_checkpoint(
    *,
    project_root: Path,
    run_id: str,
    inputs: dict[str, Any],
    environment: dict[str, Any],
    resume: bool,
) -> tuple[dict[str, Any], Path, bool]:
    path = checkpoint_path(project_root, run_id)
    if resume:
        loaded = load_checkpoint(path)
        if loaded is None:
            raise RuntimeError(f"No checkpoint found for run '{run_id}'")
        if not validate_checkpoint_schema(loaded):
            raise RuntimeError(f"Checkpoint for run '{run_id}' is invalid or incompatible")
        assert_fingerprint_matches(loaded, inputs)
        return loaded, path, True

    payload = build_checkpoint(run_id=run_id, inputs=inputs, environment=environment)
    write_checkpoint(path, payload)
    write_current_run(project_root, run_id)
    return payload, path, False


__all__ = [
    "StageFailure",
    "assert_fingerprint_matches",
    "build_checkpoint",
    "checkpoint_path",
    "initialize_or_load_checkpoint",
    "is_run_complete",
    "load_checkpoint",
    "mark_stage_completed",
    "mark_stage_failed",
    "mark_stage_skipped",
    "mark_stage_started",
    "next_stage_for_resume",
    "update_artifacts_append_only",
    "validate_checkpoint_schema",
    "write_checkpoint",
    "write_current_run",
]
