"""Type contracts and constant identifiers for bootstrap v2."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

BOOTSTRAP_EVENT_SCHEMA = "ai_stack.bootstrap.event.v1"
BOOTSTRAP_CHECKPOINT_SCHEMA = "ai_stack.bootstrap.checkpoint.v1"
BOOTSTRAP_PLAN_ID = "bootstrap-v2-linux"

STAGE_PRECHECK = "preflight.checks"
STAGE_LLMFIT_INSTALL = "llmfit.install"
STAGE_HW_DETECT = "hw.detect"
STAGE_HW_MAP = "hw.map"
STAGE_LLAMA_SYNC = "llama.sync"
STAGE_LLAMA_BUILD = "llama.build"
STAGE_MODEL_RECOMMEND = "model.recommend"
STAGE_MODEL_ACQUIRE = "model.acquire"
STAGE_SMOKE_HEALTH_MODELS = "smoke.health_models"
STAGE_STATE_PERSIST = "state.persist"

STAGE_IDS = (
    STAGE_PRECHECK,
    STAGE_LLMFIT_INSTALL,
    STAGE_HW_DETECT,
    STAGE_HW_MAP,
    STAGE_LLAMA_SYNC,
    STAGE_LLAMA_BUILD,
    STAGE_MODEL_RECOMMEND,
    STAGE_MODEL_ACQUIRE,
    STAGE_SMOKE_HEALTH_MODELS,
    STAGE_STATE_PERSIST,
)

StageId = Literal[
    "preflight.checks",
    "llmfit.install",
    "hw.detect",
    "hw.map",
    "llama.sync",
    "llama.build",
    "model.recommend",
    "model.acquire",
    "smoke.health_models",
    "state.persist",
]

RunStatus = Literal["running", "completed", "failed", "cancelled"]
StageStatus = Literal["pending", "running", "completed", "failed", "skipped"]
EventLevel = Literal["debug", "info", "warning", "error"]

EventName = Literal[
    "run.started",
    "run.resumed",
    "run.completed",
    "run.failed",
    "stage.started",
    "stage.progress",
    "stage.completed",
    "stage.failed",
    "stage.skipped",
    "checkpoint.written",
]

STABLE_ERROR_CODES = (
    "dependency_missing",
    "unsupported_os",
    "unsupported_arch",
    "unsupported_hw_profile",
    "llmfit_install_failed",
    "llama_sync_failed",
    "llama_build_failed",
    "model_install_failed",
    "smoke_health_timeout",
    "smoke_models_invalid",
    "checkpoint_write_failed",
)

TERMINAL_STAGE_STATUSES = {"completed", "failed", "skipped"}


class BootstrapEvent(TypedDict):
    schema: Literal["ai_stack.bootstrap.event.v1"]
    schema_version: Literal[1]
    run_id: str
    seq: int
    ts: str
    level: EventLevel
    event: EventName
    run_status: NotRequired[RunStatus]
    stage_id: NotRequired[StageId]
    stage_status: NotRequired[StageStatus]
    attempt: NotRequired[int]
    duration_ms: NotRequired[int]
    code: NotRequired[str]
    message: NotRequired[str]
    data: NotRequired[dict[str, Any]]


class StageCheckpoint(TypedDict):
    stage_id: StageId
    status: StageStatus
    attempt_count: int
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    input_hash: str | None
    output: dict[str, Any]
    error_code: str | None
    error_message: str | None
    retryable: bool


class BootstrapCheckpoint(TypedDict):
    schema: Literal["ai_stack.bootstrap.checkpoint.v1"]
    schema_version: Literal[1]
    run_id: str
    plan_id: Literal["bootstrap-v2-linux"]
    created_at: str
    updated_at: str
    run_status: RunStatus
    current_stage: StageId | None
    last_completed_stage: StageId | None
    inputs_fingerprint: str
    inputs: dict[str, Any]
    environment: dict[str, Any]
    artifacts: dict[str, Any]
    stages: dict[StageId, StageCheckpoint]


__all__ = [
    "BOOTSTRAP_CHECKPOINT_SCHEMA",
    "BOOTSTRAP_EVENT_SCHEMA",
    "BOOTSTRAP_PLAN_ID",
    "BootstrapCheckpoint",
    "BootstrapEvent",
    "EventName",
    "RunStatus",
    "STABLE_ERROR_CODES",
    "STAGE_IDS",
    "STAGE_HW_DETECT",
    "STAGE_HW_MAP",
    "STAGE_LLAMA_BUILD",
    "STAGE_LLAMA_SYNC",
    "STAGE_LLMFIT_INSTALL",
    "STAGE_MODEL_ACQUIRE",
    "STAGE_MODEL_RECOMMEND",
    "STAGE_PRECHECK",
    "STAGE_SMOKE_HEALTH_MODELS",
    "STAGE_STATE_PERSIST",
    "StageCheckpoint",
    "StageId",
    "StageStatus",
    "TERMINAL_STAGE_STATUSES",
]
