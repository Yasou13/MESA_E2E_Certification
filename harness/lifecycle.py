"""Executable, fail-closed run lifecycle state machine."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from harness.models import RunStatus


class InvalidTransitionError(RuntimeError):
    pass


LINEAR_TRANSITIONS = {
    RunStatus.CREATED: RunStatus.BOOTSTRAPPED,
    RunStatus.BOOTSTRAPPED: RunStatus.HARNESS_READY,
    RunStatus.HARNESS_READY: RunStatus.GT_FROZEN,
    RunStatus.GT_FROZEN: RunStatus.CONTRACT_FROZEN,
    RunStatus.CONTRACT_FROZEN: RunStatus.TEST_RUNNING,
    RunStatus.TEST_RUNNING: RunStatus.TEST_COMPLETED,
    RunStatus.TEST_COMPLETED: RunStatus.FINALIZING,
}
TERMINAL_STATUSES = {
    RunStatus.PASS_NATIVE,
    RunStatus.FAIL,
    RunStatus.BLOCKED,
    RunStatus.INVALIDATED,
}


class RunLifecycle:
    def __init__(self, run_id: str):
        if not run_id:
            raise ValueError("run_id must be non-empty")
        self.run_id = run_id
        self.status = RunStatus.CREATED
        self.history: list[dict[str, str]] = []

    def allowed_transitions(self) -> set[RunStatus]:
        if self.status in TERMINAL_STATUSES:
            return set()
        allowed = {RunStatus.FAIL, RunStatus.BLOCKED}
        linear = LINEAR_TRANSITIONS.get(self.status)
        if linear is not None:
            allowed.add(linear)
        if self.status in {
            RunStatus.GT_FROZEN,
            RunStatus.CONTRACT_FROZEN,
            RunStatus.TEST_RUNNING,
            RunStatus.TEST_COMPLETED,
            RunStatus.FINALIZING,
        }:
            allowed.add(RunStatus.INVALIDATED)
        if self.status is RunStatus.FINALIZING:
            allowed.add(RunStatus.PASS_NATIVE)
        return allowed

    def transition(
        self,
        target: RunStatus,
        *,
        at: datetime | None = None,
        reason: str | None = None,
    ) -> None:
        if target not in self.allowed_transitions():
            raise InvalidTransitionError(
                f"invalid lifecycle transition: {self.status.value} -> {target.value}"
            )
        timestamp = at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("lifecycle timestamps must be timezone-aware")
        previous = self.status
        self.status = target
        event = {
            "from": previous.value,
            "to": target.value,
            "timestamp_utc": timestamp.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        if reason:
            event["reason"] = reason
        self.history.append(event)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "status": self.status.value,
            "history": list(self.history),
        }

    def write(self, path: str | Path) -> None:
        serialized = json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        Path(path).write_text(serialized, encoding="utf-8", newline="\n")
