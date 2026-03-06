"""Bootstrap v2 stage runner with checkpointed resume."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from bootstrap.checkpoint import (
    StageFailure,
    initialize_or_load_checkpoint,
    mark_stage_completed,
    mark_stage_failed,
    mark_stage_skipped,
    mark_stage_started,
    next_stage_for_resume,
    update_artifacts_append_only,
    write_checkpoint,
)
from bootstrap.contracts import STAGE_IDS
from bootstrap.errors import StageError, StageSkipped
from bootstrap.events import EventEmitter
from bootstrap.io_utils import sha256_for_mapping
from bootstrap.paths import events_path

StageHandler = Callable[["StageContext"], dict[str, Any]]


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    handler: StageHandler
    default_failure_code: str
    retryable: bool = False


@dataclass
class StageContext:
    project_root: Path
    checkpoint: dict[str, Any]
    options: Any


class BootstrapRunner:
    def __init__(
        self,
        *,
        project_root: Path,
        run_id: str,
        inputs: dict[str, Any],
        environment: dict[str, Any],
        resume: bool,
        events_file: Optional[Path],
        options: Any,
    ) -> None:
        self.project_root = Path(project_root)
        self.run_id = run_id
        self.options = options

        payload, checkpoint_file, resumed = initialize_or_load_checkpoint(
            project_root=self.project_root,
            run_id=run_id,
            inputs=inputs,
            environment=environment,
            resume=resume,
        )
        self.checkpoint_payload = payload
        self.checkpoint_file = checkpoint_file
        self.resumed = resumed
        self.events_file = Path(events_file) if events_file else events_path(self.project_root, run_id)
        self.emitter = EventEmitter(run_id=run_id, events_file=self.events_file)

    def _emit_checkpoint_written(self, stage_id: Optional[str]) -> None:
        data = {"checkpoint": str(self.checkpoint_file)}
        self.emitter.emit(
            "checkpoint.written",
            run_status=self.checkpoint_payload.get("run_status"),
            stage_id=stage_id,
            stage_status=self.checkpoint_payload.get("stages", {}).get(stage_id, {}).get("status") if stage_id else None,
            data=data,
        )

    def _stage_input_hash(self, stage_id: str) -> str:
        material = {
            "stage_id": stage_id,
            "inputs": self.checkpoint_payload.get("inputs", {}),
            "artifacts": self.checkpoint_payload.get("artifacts", {}),
        }
        return sha256_for_mapping(material)

    def run(self, stages: list[StageDefinition]) -> dict[str, Any]:
        stage_by_id = {stage.stage_id: stage for stage in stages}
        for stage_id in STAGE_IDS:
            if stage_id not in stage_by_id:
                raise RuntimeError(f"Missing stage handler for '{stage_id}'")

        context = StageContext(
            project_root=self.project_root,
            checkpoint=self.checkpoint_payload,
            options=self.options,
        )

        if self.resumed:
            next_stage = next_stage_for_resume(self.checkpoint_payload)
            self.emitter.emit(
                "run.resumed",
                run_status=self.checkpoint_payload.get("run_status"),
                data={"from_stage": next_stage},
            )
        else:
            next_stage = STAGE_IDS[0]
            self.emitter.emit(
                "run.started",
                run_status=self.checkpoint_payload.get("run_status"),
                data={"stage_count": len(STAGE_IDS)},
            )

        if next_stage is None and self.checkpoint_payload.get("run_status") == "completed":
            self.emitter.emit("run.completed", run_status="completed")
            return self.checkpoint_payload

        start_index = STAGE_IDS.index(next_stage) if next_stage is not None else len(STAGE_IDS)

        for stage_id in STAGE_IDS[start_index:]:
            stage = stage_by_id[stage_id]
            current_status = self.checkpoint_payload["stages"][stage_id].get("status")
            if current_status in {"completed", "skipped"}:
                continue

            input_hash = self._stage_input_hash(stage_id)
            attempt = mark_stage_started(self.checkpoint_payload, stage_id, input_hash=input_hash)
            write_checkpoint(self.checkpoint_file, self.checkpoint_payload)
            self._emit_checkpoint_written(stage_id)
            self.emitter.emit(
                "stage.started",
                run_status=self.checkpoint_payload.get("run_status"),
                stage_id=stage_id,
                stage_status="running",
                attempt=attempt,
            )

            try:
                output = stage.handler(context)
                if not isinstance(output, dict):
                    raise RuntimeError("Stage handler output must be a dict")
                artifact_updates = output.get("artifacts", {})
                if isinstance(artifact_updates, dict) and artifact_updates:
                    update_artifacts_append_only(self.checkpoint_payload, artifact_updates)
                duration_ms = mark_stage_completed(self.checkpoint_payload, stage_id, output=output)
                write_checkpoint(self.checkpoint_file, self.checkpoint_payload)
                self._emit_checkpoint_written(stage_id)
                self.emitter.emit(
                    "stage.completed",
                    run_status=self.checkpoint_payload.get("run_status"),
                    stage_id=stage_id,
                    stage_status="completed",
                    duration_ms=duration_ms,
                )
            except StageSkipped as exc:
                duration_ms = mark_stage_skipped(self.checkpoint_payload, stage_id, reason=exc.reason)
                write_checkpoint(self.checkpoint_file, self.checkpoint_payload)
                self._emit_checkpoint_written(stage_id)
                self.emitter.emit(
                    "stage.skipped",
                    run_status=self.checkpoint_payload.get("run_status"),
                    stage_id=stage_id,
                    stage_status="skipped",
                    duration_ms=duration_ms,
                    message=exc.reason,
                )
            except StageError as exc:
                failure = StageFailure(
                    code=exc.code,
                    message=exc.message,
                    retryable=bool(exc.retryable or stage.retryable),
                )
                duration_ms = mark_stage_failed(self.checkpoint_payload, stage_id, failure)
                write_checkpoint(self.checkpoint_file, self.checkpoint_payload)
                self._emit_checkpoint_written(stage_id)
                self.emitter.emit(
                    "stage.failed",
                    level="error",
                    run_status=self.checkpoint_payload.get("run_status"),
                    stage_id=stage_id,
                    stage_status="failed",
                    duration_ms=duration_ms,
                    code=failure.code,
                    message=failure.message,
                )
                self.emitter.emit(
                    "run.failed",
                    level="error",
                    run_status="failed",
                    code=failure.code,
                    message=failure.message,
                    data={"failed_stage": stage_id},
                )
                raise
            except Exception as exc:  # pragma: no cover - defensive boundary
                message = str(exc) or exc.__class__.__name__
                failure = StageFailure(
                    code=stage.default_failure_code,
                    message=message,
                    retryable=stage.retryable,
                )
                duration_ms = mark_stage_failed(self.checkpoint_payload, stage_id, failure)
                write_checkpoint(self.checkpoint_file, self.checkpoint_payload)
                self._emit_checkpoint_written(stage_id)
                self.emitter.emit(
                    "stage.failed",
                    level="error",
                    run_status="failed",
                    stage_id=stage_id,
                    stage_status="failed",
                    duration_ms=duration_ms,
                    code=failure.code,
                    message=failure.message,
                )
                self.emitter.emit(
                    "run.failed",
                    level="error",
                    run_status="failed",
                    code=failure.code,
                    message=failure.message,
                    data={"failed_stage": stage_id},
                )
                raise StageError(code=failure.code, message=failure.message, retryable=failure.retryable) from exc

        self.emitter.emit("run.completed", run_status="completed")
        return self.checkpoint_payload


__all__ = ["BootstrapRunner", "StageContext", "StageDefinition"]
