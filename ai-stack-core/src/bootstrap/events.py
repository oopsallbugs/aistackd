"""Bootstrap event emission (stderr + JSONL mirror)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Optional

from bootstrap.contracts import BOOTSTRAP_EVENT_SCHEMA
from bootstrap.io_utils import append_jsonl, utc_now_iso


class EventEmitter:
    """Emit contract-compliant events with per-run monotonic sequence numbers."""

    def __init__(self, *, run_id: str, events_file: Path, mirror_stderr: bool = True) -> None:
        self.run_id = run_id
        self.events_file = Path(events_file)
        self.mirror_stderr = bool(mirror_stderr)
        self.seq = self._load_last_seq()

    def _load_last_seq(self) -> int:
        if not self.events_file.exists():
            return 0
        last_seq = 0
        try:
            with self.events_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        seq_value = payload.get("seq")
                        if isinstance(seq_value, int) and seq_value > last_seq:
                            last_seq = seq_value
        except (OSError, ValueError, TypeError):
            return 0
        return last_seq

    def emit(
        self,
        event: str,
        *,
        level: str = "info",
        run_status: Optional[str] = None,
        stage_id: Optional[str] = None,
        stage_status: Optional[str] = None,
        attempt: Optional[int] = None,
        duration_ms: Optional[int] = None,
        code: Optional[str] = None,
        message: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        self.seq += 1
        payload: dict[str, Any] = {
            "schema": BOOTSTRAP_EVENT_SCHEMA,
            "schema_version": 1,
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": utc_now_iso(),
            "level": level,
            "event": event,
        }
        if run_status is not None:
            payload["run_status"] = run_status
        if stage_id is not None:
            payload["stage_id"] = stage_id
        if stage_status is not None:
            payload["stage_status"] = stage_status
        if attempt is not None:
            payload["attempt"] = attempt
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if code is not None:
            payload["code"] = code
        if message is not None:
            payload["message"] = message
        if data is not None:
            payload["data"] = data

        append_jsonl(self.events_file, payload)
        if self.mirror_stderr:
            print(f"[bootstrap.event] {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
        return payload


__all__ = ["EventEmitter"]
