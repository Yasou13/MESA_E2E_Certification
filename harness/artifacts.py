"""Immutable raw-first run artifact storage with scored-lane ordering guards."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.models import RawRequestRecord, RawResponseRecord, SHA256_PATTERN


QUERY_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class ArtifactStoreError(RuntimeError):
    pass


class ImmutableArtifactError(ArtifactStoreError):
    pass


class ArtifactOrderError(ArtifactStoreError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactStoreError(f"value is not canonical JSON: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AnswerExecutionCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    query_id: str = Field(min_length=1)
    timestamp_utc: datetime
    exact_model_visible_context: Any
    context_evidence_ids: list[str]
    context_sha256: str = Field(pattern=SHA256_PATTERN)
    system_prompt: str
    user_prompt: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    request_parameters: dict[str, Any]
    raw_response: Any
    parsed_response: dict[str, Any]
    context_contract_version: str = Field(min_length=1)

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        return value

    @model_validator(mode="after")
    def context_hash_must_match(self) -> "AnswerExecutionCapture":
        observed = _sha256_bytes(canonical_json_bytes(self.exact_model_visible_context))
        if observed != self.context_sha256:
            raise ValueError(
                f"context SHA-256 mismatch: expected {self.context_sha256}, observed {observed}"
            )
        return self

    @classmethod
    def from_context(cls, **values: Any) -> "AnswerExecutionCapture":
        context = values["exact_model_visible_context"]
        return cls(
            **values,
            context_sha256=_sha256_bytes(canonical_json_bytes(context)),
        )


class RunArtifactStore:
    def __init__(
        self,
        run_dir: str | Path,
        run_id: str,
        *,
        max_response_bytes: int = 16 * 1024 * 1024,
    ):
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.max_response_bytes = max_response_bytes
        if not run_id or self.run_dir.name != run_id:
            raise ArtifactStoreError("run directory basename must equal run_id")
        if max_response_bytes <= 0:
            raise ArtifactStoreError("max_response_bytes must be positive")

    @property
    def raw_retrieval_dir(self) -> Path:
        return self.run_dir / "raw" / "retrieval"

    @property
    def raw_answers_dir(self) -> Path:
        return self.run_dir / "raw" / "answers"

    @property
    def scored_retrieval_dir(self) -> Path:
        return self.run_dir / "scored" / "retrieval"

    @property
    def scored_answers_dir(self) -> Path:
        return self.run_dir / "scored" / "answers"

    @property
    def marker_path(self) -> Path:
        return self.run_dir / ".mesa-e2e-layout.json"

    def initialize(self) -> None:
        if self.run_dir.exists() and any(self.run_dir.iterdir()):
            if not self.marker_path.is_file():
                raise ImmutableArtifactError(
                    "refusing to initialize a non-empty unowned run directory"
                )
            marker = json.loads(self.marker_path.read_text(encoding="utf-8"))
            if marker.get("run_id") != self.run_id:
                raise ImmutableArtifactError("run layout marker has a different run_id")
        for directory in (
            self.raw_retrieval_dir,
            self.raw_answers_dir,
            self.scored_retrieval_dir,
            self.scored_answers_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.marker_path.exists():
            self._write_immutable_json(
                self.marker_path,
                {"schema_version": "1.0", "run_id": self.run_id},
            )

    def _query_path(self, directory: Path, query_id: str) -> Path:
        if QUERY_ID.fullmatch(query_id) is None:
            raise ArtifactStoreError(f"unsafe query_id for artifact path: {query_id!r}")
        return directory / f"{query_id}.json"

    @staticmethod
    def _sidecar(path: Path) -> Path:
        return path.with_suffix(path.suffix + ".SHA256")

    def _verify_seal(self, path: Path) -> str:
        sidecar = self._sidecar(path)
        if not path.is_file() or not sidecar.is_file():
            raise ArtifactOrderError(f"raw artifact or seal is missing: {path.name}")
        parts = sidecar.read_text(encoding="utf-8").strip().split()
        observed = _sha256_bytes(path.read_bytes())
        if len(parts) != 2 or parts[1] != path.name or parts[0] != observed:
            raise ImmutableArtifactError(f"sealed artifact mutated: {path.name}")
        return observed

    def _write_immutable_json(self, path: Path, payload: Any) -> Path:
        serialized = (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if path.exists():
            if path.read_bytes() != serialized:
                raise ImmutableArtifactError(f"artifact already exists with new bytes: {path}")
            self._verify_seal(path)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(serialized)
        digest = _sha256_bytes(serialized)
        self._sidecar(path).write_text(
            f"{digest}  {path.name}\n", encoding="utf-8", newline="\n"
        )
        return path

    def persist_raw_retrieval(
        self,
        *,
        query_id: str,
        request: dict[str, Any],
        response: dict[str, Any],
        transport_status: int,
        timestamp_utc: datetime,
        latency_ms: float,
        runtime_lock_sha256: str,
    ) -> Path:
        response_bytes = canonical_json_bytes(response)
        if len(response_bytes) > self.max_response_bytes:
            raise ArtifactStoreError(
                f"response exceeds bounded capture limit: {len(response_bytes)}"
            )
        request_record = RawRequestRecord(
            query_id=query_id,
            request=request,
            timestamp_utc=timestamp_utc,
            runtime_lock_sha256=runtime_lock_sha256,
            request_sha256=_sha256_bytes(canonical_json_bytes(request)),
        )
        response_record = RawResponseRecord(
            query_id=query_id,
            transport_status=transport_status,
            response=response,
            timestamp_utc=timestamp_utc,
            latency_ms=latency_ms,
            response_sha256=_sha256_bytes(response_bytes),
        )
        payload = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "lane": "retrieval",
            "query_id": query_id,
            "request": request_record.model_dump(mode="json"),
            "response": response_record.model_dump(mode="json"),
        }
        return self._write_immutable_json(
            self._query_path(self.raw_retrieval_dir, query_id), payload
        )

    def persist_raw_answer(self, capture: AnswerExecutionCapture) -> Path:
        payload = {
            "run_id": self.run_id,
            "lane": "answers",
            **capture.model_dump(mode="json"),
        }
        return self._write_immutable_json(
            self._query_path(self.raw_answers_dir, capture.query_id), payload
        )

    def persist_oracle_audit(self, report: dict[str, Any]) -> Path:
        status = report.get("status")
        findings = report.get("findings")
        finding_count = report.get("finding_count")
        if status not in {"PASS", "FAIL"} or not isinstance(findings, list):
            raise ArtifactStoreError("invalid oracle audit report")
        if finding_count != len(findings):
            raise ArtifactStoreError("oracle audit finding_count mismatch")
        return self._write_immutable_json(
            self.run_dir / "oracle-leakage-audit.json", report
        )

    def _require_passing_oracle_audit(self) -> None:
        path = self.run_dir / "oracle-leakage-audit.json"
        self._verify_seal(path)
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("status") != "PASS" or report.get("finding_count") != 0:
            raise ArtifactOrderError(
                f"oracle audit must PASS before scoring: {report.get('status')}"
            )

    def persist_scored(
        self,
        *,
        lane: Literal["retrieval", "answers"],
        query_id: str,
        score: dict[str, Any],
    ) -> Path:
        self._require_passing_oracle_audit()
        raw_dir = self.raw_retrieval_dir if lane == "retrieval" else self.raw_answers_dir
        scored_dir = (
            self.scored_retrieval_dir if lane == "retrieval" else self.scored_answers_dir
        )
        raw_path = self._query_path(raw_dir, query_id)
        raw_sha256 = self._verify_seal(raw_path)
        payload = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "lane": lane,
            "query_id": query_id,
            "raw_artifact_path": raw_path.relative_to(self.run_dir).as_posix(),
            "raw_artifact_sha256": raw_sha256,
            "oracle_audit_status": "PASS",
            "score": score,
        }
        return self._write_immutable_json(
            self._query_path(scored_dir, query_id), payload
        )
