"""Operational health, resource telemetry, and runtime identity artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.models import SHA256_PATTERN


class OperationalStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class HealthPhase(str, Enum):
    PRE_TEST = "PRE_TEST"
    POST_TEST = "POST_TEST"


class OperationalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class ServiceHealth(OperationalModel):
    name: str = Field(min_length=1)
    status: OperationalStatus
    restarts: int = Field(ge=0)
    oom_killed: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class HealthSnapshot(OperationalModel):
    schema_version: str = "1.0"
    run_id: str = Field(min_length=1)
    phase: HealthPhase
    timestamp_utc: datetime
    status: OperationalStatus
    provider_reachable: Optional[bool]
    services: list[ServiceHealth]
    host_metrics: dict[str, float | int]
    reasons: list[str]

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _aware(value, "timestamp_utc")


class ResourceSample(OperationalModel):
    schema_version: str = "1.0"
    run_id: str = Field(min_length=1)
    timestamp_utc: datetime
    host_available_ram_mb: float = Field(ge=0)
    mesa_rss_mb: float = Field(ge=0)
    swap_used_mb: float = Field(ge=0)
    disk_used_mb: float = Field(ge=0)
    provider_requests: int = Field(ge=0)
    provider_retries: int = Field(ge=0)
    provider_timeouts: int = Field(ge=0)
    container_restart_count: int = Field(ge=0)
    oom_killed_count: int = Field(ge=0)
    provider_expected_requests: Optional[int] = Field(default=None, ge=0)

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _aware(value, "timestamp_utc")


class ResourcePressureEvent(OperationalModel):
    schema_version: str = "1.0"
    run_id: str = Field(min_length=1)
    timestamp_utc: datetime
    event_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    observed: dict[str, Any]
    action: str = Field(min_length=1)

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _aware(value, "timestamp_utc")


SECRET_FIELD_NAMES = {
    "access_token",
    "api_key",
    "authorization",
    "bearer_token",
    "password",
    "refresh_token",
    "secret",
}


def _find_secret_field(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SECRET_FIELD_NAMES:
                return str(key)
            found = _find_secret_field(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_secret_field(nested)
            if found:
                return found
    return None


class RuntimeLock(OperationalModel):
    schema_version: str = "1.0"
    run_id: str = Field(min_length=1)
    created_at_utc: datetime
    mesa_repository_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    mesa_data_repository_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    e2e_repository_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    runtime_identity: dict[str, Any]
    provider_identity: dict[str, Any]
    config_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("created_at_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _aware(value, "created_at_utc")

    @model_validator(mode="after")
    def identities_must_not_contain_secrets(self) -> "RuntimeLock":
        forbidden = _find_secret_field(
            {
                "runtime_identity": self.runtime_identity,
                "provider_identity": self.provider_identity,
            }
        )
        if forbidden:
            raise ValueError(f"secret field is forbidden in runtime lock: {forbidden}")
        return self


def capture_health_snapshot(
    *,
    run_id: str,
    phase: HealthPhase,
    timestamp_utc: datetime,
    services: list[ServiceHealth],
    provider_reachable: Optional[bool],
    host_metrics: dict[str, float | int],
) -> HealthSnapshot:
    reasons: list[str] = []
    if not services:
        reasons.append("no required service observations")
    if provider_reachable is None:
        reasons.append("provider reachability unverified")
    failed_services = [
        service.name
        for service in services
        if service.status is OperationalStatus.FAIL
        or service.restarts > 0
        or service.oom_killed
    ]
    unverified_services = [
        service.name
        for service in services
        if service.status is OperationalStatus.UNVERIFIED
    ]
    if failed_services or provider_reachable is False:
        status = OperationalStatus.FAIL
        if failed_services:
            reasons.append(f"failed services: {sorted(failed_services)}")
        if provider_reachable is False:
            reasons.append("provider unreachable")
    elif reasons or unverified_services:
        status = OperationalStatus.UNVERIFIED
        if unverified_services:
            reasons.append(f"unverified services: {sorted(unverified_services)}")
    else:
        status = OperationalStatus.PASS
        reasons.append("all observed services and provider checks passed")
    return HealthSnapshot(
        run_id=run_id,
        phase=phase,
        timestamp_utc=timestamp_utc,
        status=status,
        provider_reachable=provider_reachable,
        services=services,
        host_metrics=host_metrics,
        reasons=reasons,
    )


def write_health_snapshot(snapshot: HealthSnapshot, path: str | Path) -> None:
    serialized = json.dumps(
        snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    Path(path).write_text(serialized, encoding="utf-8", newline="\n")


def verify_health_artifacts(run_dir: Path, run_id: str) -> dict[str, object]:
    """Re-evaluate measurements; never accept a serialized status by itself."""
    try:
        for name, phase in (("health-pre-test.json", HealthPhase.PRE_TEST),
                            ("health-post-test.json", HealthPhase.POST_TEST)):
            snapshot = HealthSnapshot.model_validate_json((run_dir / name).read_text())
            if snapshot.run_id != run_id or snapshot.phase != phase:
                raise ValueError(f"wrong identity/phase in {name}")
            recomputed = capture_health_snapshot(
                run_id=run_id, phase=phase, timestamp_utc=snapshot.timestamp_utc,
                services=snapshot.services, provider_reachable=snapshot.provider_reachable,
                host_metrics=snapshot.host_metrics,
            )
            if recomputed.status != OperationalStatus.PASS or not snapshot.host_metrics:
                raise ValueError(f"unverified health measurements in {name}")
        samples = [ResourceSample.model_validate_json(line) for line in
                   (run_dir / "resource-telemetry.jsonl").read_text().splitlines() if line.strip()]
        events = [ResourcePressureEvent.model_validate_json(line) for line in
                  (run_dir / "resource-pressure-events.jsonl").read_text().splitlines() if line.strip()]
        if any(r.run_id != run_id for r in [*samples, *events]):
            raise ValueError("resource measurement run_id mismatch")
        result = evaluate_resource_status(samples, events)
        return {**result, "run_id": run_id}
    except (OSError, ValueError) as exc:
        return {"schema_version": "1.0", "run_id": run_id,
                "status": "UNVERIFIED", "reasons": [f"missing/invalid health measurement: {exc}"]}


def evaluate_resource_status(
    samples: list[ResourceSample], events: list[ResourcePressureEvent]
) -> dict[str, object]:
    if not samples:
        return {
            "schema_version": "1.0",
            "status": "UNVERIFIED",
            "reasons": ["resource telemetry is missing"],
        }
    reasons: list[str] = []
    if any(sample.oom_killed_count > 0 for sample in samples):
        reasons.append("OOMKilled observed")
    if any(sample.container_restart_count > 0 for sample in samples):
        reasons.append("container restart observed")
    if any(event.severity.casefold() == "critical" for event in events):
        reasons.append("critical resource pressure event observed")
    if any(
        sample.provider_expected_requests is not None
        and sample.provider_requests > 2 * sample.provider_expected_requests
        for sample in samples
    ):
        reasons.append("provider request budget exceeded 2x expected")
    return {
        "schema_version": "1.0",
        "status": "FAIL" if reasons else "PASS",
        "reasons": reasons or ["no hard resource failure observed"],
    }


def _write_jsonl(records: list[OperationalModel], path: Path) -> None:
    lines = [
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for record in records
    ]
    path.write_text(
        ("\n".join(lines) + "\n") if lines else "",
        encoding="utf-8",
        newline="\n",
    )


def write_resource_artifacts(
    samples: list[ResourceSample],
    events: list[ResourcePressureEvent],
    output_dir: str | Path,
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    telemetry_path = destination / "resource-telemetry.jsonl"
    events_path = destination / "resource-pressure-events.jsonl"
    _write_jsonl(samples, telemetry_path)
    _write_jsonl(events, events_path)
    return telemetry_path, events_path


def write_runtime_lock(
    runtime_lock: RuntimeLock, output_dir: str | Path
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "mesa-runtime-lock.json"
    serialized = (
        json.dumps(
            runtime_lock.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(serialized)
    digest = hashlib.sha256(serialized).hexdigest()
    sidecar = destination / "mesa-runtime-lock.SHA256"
    sidecar.write_text(
        f"{digest}  {path.name}\n", encoding="utf-8", newline="\n"
    )
    return path, sidecar
