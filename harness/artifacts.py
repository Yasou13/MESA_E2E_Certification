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


class CertifiedAnswerExecutionCapture(BaseModel):
    """Exact provider-boundary capture used by authoritative answer scoring.

    The legacy ``AnswerExecutionCapture`` remains readable for historical and
    negative tests, but only this v2 schema carries the current-run/runtime and
    byte-exact request bindings required for production scoring.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    run_id: str = Field(min_length=1)
    lane: Literal["answers"] = "answers"
    query_id: str = Field(min_length=1)
    timestamp_utc: datetime
    capture_origin: Literal["harness.answer_execution.provider_boundary"]
    source_context_contract: Literal["GET /v4/sessions/{session_id}/context"]
    context_contract_version: Literal["mesa-e2e.context.v1"]
    mesa_sha: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    tenant_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    dataset_ids: list[str] = Field(min_length=1)
    exact_model_visible_context: str
    context_evidence_ids: list[str]
    context_sha256: str = Field(pattern=SHA256_PATTERN)
    system_prompt: str
    system_prompt_sha256: str = Field(pattern=SHA256_PATTERN)
    question: str = Field(min_length=1)
    question_sha256: str = Field(pattern=SHA256_PATTERN)
    answer_instruction: str = Field(min_length=1)
    answer_instruction_sha256: str = Field(pattern=SHA256_PATTERN)
    user_prompt: str
    user_prompt_sha256: str = Field(pattern=SHA256_PATTERN)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    request_parameters: dict[str, Any]
    exact_provider_request: dict[str, Any]
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    raw_provider_response: dict[str, Any]
    response_sha256: str = Field(pattern=SHA256_PATTERN)
    provider_exchange_sha256: str = Field(pattern=SHA256_PATTERN)
    parsed_response: dict[str, Any]

    @field_validator("timestamp_utc")
    @classmethod
    def certified_timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        return value

    @model_validator(mode="after")
    def exact_hashes_must_match(self) -> "CertifiedAnswerExecutionCapture":
        expected = {
            "context_sha256": _sha256_bytes(
                self.exact_model_visible_context.encode("utf-8")
            ),
            "system_prompt_sha256": _sha256_bytes(self.system_prompt.encode("utf-8")),
            "question_sha256": _sha256_bytes(self.question.encode("utf-8")),
            "answer_instruction_sha256": _sha256_bytes(
                self.answer_instruction.encode("utf-8")
            ),
            "user_prompt_sha256": _sha256_bytes(self.user_prompt.encode("utf-8")),
            "request_sha256": _sha256_bytes(
                canonical_json_bytes(self.exact_provider_request)
            ),
            "response_sha256": _sha256_bytes(
                canonical_json_bytes(self.raw_provider_response)
            ),
        }
        for field, observed in expected.items():
            if getattr(self, field) != observed:
                raise ValueError(f"{field} mismatch: expected {observed}")
        messages = self.exact_provider_request.get("messages")
        if messages != [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_prompt},
        ]:
            raise ValueError("exact provider messages do not match captured prompts")
        if self.exact_provider_request.get("model") != self.model:
            raise ValueError("exact provider request model mismatch")
        expected_user_prompt = (
            f"{self.answer_instruction}\n\nQUESTION:\n{self.question}\n\n"
            f"MODEL_VISIBLE_CONTEXT:\n{self.exact_model_visible_context}"
        )
        if self.user_prompt != expected_user_prompt:
            raise ValueError(
                "provider user prompt is not the exact captured composition"
            )
        for key, value in self.request_parameters.items():
            if self.exact_provider_request.get(key) != value:
                raise ValueError(f"exact provider request parameter mismatch: {key}")
        if self.exact_model_visible_context not in self.user_prompt:
            raise ValueError(
                "exact model-visible context is absent from provider user prompt"
            )
        if len(self.context_evidence_ids) != len(set(self.context_evidence_ids)):
            raise ValueError("context_evidence_ids contains duplicates")
        if len(self.dataset_ids) != len(set(self.dataset_ids)) or any(
            not dataset_id for dataset_id in self.dataset_ids
        ):
            raise ValueError("dataset_ids contains empty or duplicate identities")
        return self


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
    def raw_provider_dir(self) -> Path:
        return self.run_dir / "raw" / "provider"

    @property
    def raw_scope_dir(self) -> Path:
        return self.run_dir / "raw" / "scope"

    @property
    def raw_graph_dir(self) -> Path:
        return self.run_dir / "raw" / "graph"

    @property
    def raw_state_dir(self) -> Path:
        return self.run_dir / "raw" / "state"

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
            self.raw_provider_dir,
            self.raw_scope_dir,
            self.raw_graph_dir,
            self.raw_state_dir,
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
                raise ImmutableArtifactError(
                    f"artifact already exists with new bytes: {path}"
                )
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

    def persist_raw_answer(
        self, capture: AnswerExecutionCapture | CertifiedAnswerExecutionCapture
    ) -> Path:
        payload = {
            "run_id": self.run_id,
            "lane": "answers",
            **capture.model_dump(mode="json"),
        }
        if isinstance(capture, CertifiedAnswerExecutionCapture):
            if capture.run_id != self.run_id:
                raise ArtifactStoreError("certified answer capture run_id mismatch")
        return self._write_immutable_json(
            self._query_path(self.raw_answers_dir, capture.query_id), payload
        )

    def persist_raw_provider_exchange(
        self,
        *,
        query_id: str,
        timestamp_utc: datetime,
        provider: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> tuple[Path, str]:
        """Seal the exact provider exchange before response parsing."""

        response_bytes = canonical_json_bytes(response)
        if len(response_bytes) > self.max_response_bytes:
            raise ArtifactStoreError(
                f"provider response exceeds bounded capture limit: {len(response_bytes)}"
            )
        if timestamp_utc.tzinfo is None or timestamp_utc.utcoffset() is None:
            raise ArtifactStoreError(
                "provider exchange timestamp must be timezone-aware"
            )
        payload = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "lane": "provider_exchange",
            "query_id": query_id,
            "timestamp_utc": timestamp_utc.isoformat(),
            "provider": provider,
            "request": request,
            "request_sha256": _sha256_bytes(canonical_json_bytes(request)),
            "response": response,
            "response_sha256": _sha256_bytes(response_bytes),
        }
        path = self._write_immutable_json(
            self._query_path(self.raw_provider_dir, query_id), payload
        )
        return path, self._verify_seal(path)

    def persist_raw_scope(
        self,
        case_id: str,
        payload: dict[str, Any],
    ) -> tuple[Path, str]:
        path = self.raw_scope_dir / f"{case_id}.json"
        self._write_immutable_json(path, payload)
        return path, self._verify_seal(path)

    def persist_raw_graph(
        self,
        filename: str,
        payload: dict[str, Any],
    ) -> tuple[Path, str]:
        path = self.raw_graph_dir / filename
        self._write_immutable_json(path, payload)
        return path, self._verify_seal(path)

    def persist_raw_state_proof(
        self,
        filename: str,
        payload: dict[str, Any],
    ) -> tuple[Path, str]:
        path = self.raw_state_dir / filename
        self._write_immutable_json(path, payload)
        return path, self._verify_seal(path)

    def compute_raw_manifest(self) -> dict[str, Any]:
        entries: list[dict[str, str]] = []
        for lane_dir in (
            self.raw_retrieval_dir,
            self.raw_answers_dir,
            self.raw_provider_dir,
            self.raw_scope_dir,
            self.raw_graph_dir,
            self.raw_state_dir,
        ):
            if lane_dir.is_dir():
                for json_file in sorted(lane_dir.glob("*.json")):
                    sha = self._verify_seal(json_file)
                    payload = json.loads(json_file.read_text(encoding="utf-8"))
                    if (
                        not isinstance(payload, dict)
                        or payload.get("run_id") != self.run_id
                    ):
                        raise ArtifactStoreError(
                            f"raw artifact run_id mismatch: {json_file.name}"
                        )
                    rel_path = json_file.relative_to(self.run_dir).as_posix()
                    entries.append({"path": rel_path, "sha256": sha})
        entries.sort(key=lambda item: item["path"])
        manifest_hash = _sha256_bytes(canonical_json_bytes(entries))
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "manifest_hash": manifest_hash,
            "entries": entries,
        }

    def persist_oracle_audit(self, report: dict[str, Any]) -> Path:
        status = report.get("status")
        findings = report.get("findings")
        finding_count = report.get("finding_count")
        if status not in {"PASS", "FAIL"} or not isinstance(findings, list):
            raise ArtifactStoreError("invalid oracle audit report")
        if finding_count != len(findings):
            raise ArtifactStoreError("oracle audit finding_count mismatch")

        report_copy = dict(report)
        if not report_copy.get("raw_manifest_hash"):
            raw_man = self.compute_raw_manifest()
            report_copy["raw_manifest_hash"] = raw_man["manifest_hash"]
            report_copy["raw_artifacts"] = raw_man["entries"]
        if not report_copy.get("run_id"):
            report_copy["run_id"] = self.run_id

        return self._write_immutable_json(
            self.run_dir / "oracle-leakage-audit.json", report_copy
        )

    def _require_passing_oracle_audit(self) -> None:
        path = self.run_dir / "oracle-leakage-audit.json"
        self._verify_seal(path)
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("run_id") != self.run_id:
            raise ArtifactOrderError("oracle audit run_id mismatch")
        if report.get("status") != "PASS" or report.get("finding_count") != 0:
            raise ArtifactOrderError(
                f"oracle audit must PASS before scoring: {report.get('status')}"
            )
        current_man = self.compute_raw_manifest()
        audited_hash = report.get("raw_manifest_hash")
        if current_man["manifest_hash"] != audited_hash:
            raise ArtifactOrderError(
                f"ORACLE_AUDIT_STALE: raw manifest hash {current_man['manifest_hash']} does not match audited hash {audited_hash}"
            )

    def persist_scored(
        self,
        *,
        lane: Literal["retrieval", "answers"],
        query_id: str,
        score: dict[str, Any],
    ) -> Path:
        self._require_passing_oracle_audit()
        raw_dir = (
            self.raw_retrieval_dir if lane == "retrieval" else self.raw_answers_dir
        )
        scored_dir = (
            self.scored_retrieval_dir
            if lane == "retrieval"
            else self.scored_answers_dir
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
