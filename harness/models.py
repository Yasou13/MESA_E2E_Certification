"""Strict, versioned data models for the Profile B certification harness."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    BOOTSTRAPPED = "BOOTSTRAPPED"
    HARNESS_READY = "HARNESS_READY"
    GT_FROZEN = "GT_FROZEN"
    CONTRACT_FROZEN = "CONTRACT_FROZEN"
    TEST_RUNNING = "TEST_RUNNING"
    TEST_COMPLETED = "TEST_COMPLETED"
    FINALIZING = "FINALIZING"
    PASS_NATIVE = "PASS_NATIVE"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"


class ScoringStatus(str, Enum):
    HIT = "HIT"
    MISS = "MISS"
    PARTIAL = "PARTIAL"
    PASS = "PASS"
    FAIL = "FAIL"
    UNRESOLVED = "UNRESOLVED"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    MAPPING_INTEGRITY_ERROR = "MAPPING_INTEGRITY_ERROR"
    NO_ANSWER_EVALUATED_IN_ANSWER_STAGE = "NO_ANSWER_EVALUATED_IN_ANSWER_STAGE"


class InfrastructureStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"


class PatternMode(str, Enum):
    LITERAL = "literal"
    REGEX = "regex"
    ALL_OF = "all_of"
    ANY_OF = "any_of"


class HarnessModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionedRecord(HarnessModel):
    schema_version: str = "1.0"


class ExactSourceSpan(HarnessModel):
    source_chunk_id: str = Field(min_length=1)
    span_id: Optional[str] = None
    exact_text: str


class RequiredFact(HarnessModel):
    fact_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    supported_by: list[ExactSourceSpan] = Field(default_factory=list)


class EvidenceGroup(HarnessModel):
    group_id: str = Field(min_length=1)
    acceptable_source_chunk_ids: list[str] = Field(default_factory=list)


class AnswerPattern(HarnessModel):
    mode: PatternMode
    value: Optional[str] = None
    values: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_payload(self) -> "AnswerPattern":
        if self.mode in {PatternMode.LITERAL, PatternMode.REGEX}:
            if not self.value or self.values:
                raise ValueError(f"{self.mode.value} requires value and forbids values")
            if self.mode is PatternMode.REGEX:
                try:
                    re.compile(self.value)
                except re.error as exc:
                    raise ValueError(f"invalid answer regex: {exc}") from exc
        elif not self.values or self.value is not None:
            raise ValueError(f"{self.mode.value} requires values and forbids value")
        if any(not item for item in self.fact_ids):
            raise ValueError("fact_ids must contain only non-empty IDs")
        return self


class GroundTruthItem(HarnessModel):
    query_id: str = Field(min_length=1)
    query_class: str
    question: str
    expected_source_chunk_ids: list[str] = Field(default_factory=list)
    evidence_groups: list[EvidenceGroup] = Field(default_factory=list)
    required_facts: list[RequiredFact] = Field(default_factory=list)
    acceptable_answer_patterns: list[AnswerPattern] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    is_answerable: bool = True

    @field_validator("acceptable_answer_patterns", mode="before")
    @classmethod
    def make_legacy_pattern_semantics_explicit(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [
            {"mode": PatternMode.LITERAL.value, "value": item}
            if isinstance(item, str)
            else item
            for item in value
        ]


class MESAProvenanceItem(HarnessModel):
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    source_id: Optional[str] = None
    score: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResultItem(HarnessModel):
    rank: int = Field(ge=1)
    mesa_chunk_id: str = Field(min_length=1)
    document_id: Optional[str] = None
    text: str = ""
    score: float = 0.0
    provenance: list[MESAProvenanceItem] = Field(default_factory=list)


class RawRequestRecord(VersionedRecord):
    query_id: str = Field(min_length=1)
    request: dict[str, Any]
    timestamp_utc: datetime
    runtime_lock_sha256: str = Field(pattern=SHA256_PATTERN)
    request_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        return value


class RawResponseRecord(VersionedRecord):
    query_id: str = Field(min_length=1)
    transport_status: int = Field(ge=100, le=599)
    response: dict[str, Any]
    timestamp_utc: datetime
    latency_ms: float = Field(ge=0)
    response_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        return value


class RetrievedEvidence(VersionedRecord):
    rank: int = Field(ge=1)
    mesa_chunk_id: str = Field(min_length=1)
    source_chunk_id: str = Field(min_length=1)
    text: str = ""
    score: Optional[float] = None


class RetrievalScore(VersionedRecord):
    query_id: str
    query_class: str
    is_answerable: bool
    status: ScoringStatus
    rank: Optional[int] = None
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    group_coverage_at_5: float = 1.0
    complete_evidence_at_5: float = 1.0
    normalized_retrieved_chunk_ids: list[str] = Field(default_factory=list)
    matching_chunk_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class AnswerClaim(HarnessModel):
    fact_ids: list[str] = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_chunk_ids: list[str] = Field(min_length=1)


class AnswerResponse(HarnessModel):
    answer: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    claims: list[AnswerClaim] = Field(default_factory=list)


class AnswerScore(VersionedRecord):
    query_id: str
    is_answerable: bool
    status: ScoringStatus
    reasons: list[str] = Field(default_factory=list)
    grounded_pass: bool = False
    evidence_supported: bool = False
    facts_satisfied: bool = False
    forbidden_claims_absent: bool = True


class ArtifactReference(VersionedRecord):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    producer: Optional[str] = None
    phase: Optional[str] = None
    source_run_id: Optional[str] = None
    immutable: bool = False
    sealed: bool = False
