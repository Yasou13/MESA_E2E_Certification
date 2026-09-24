from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from harness.models import (
    ArtifactReference,
    GateStatus,
    InfrastructureStatus,
    RawRequestRecord,
    RawResponseRecord,
    RetrievedEvidence,
    RunStatus,
    ScoringStatus,
)


def test_core_status_enums_are_explicit() -> None:
    assert RunStatus.CONTRACT_FROZEN.value == "CONTRACT_FROZEN"
    assert GateStatus.UNVERIFIED.value == "UNVERIFIED"
    assert ScoringStatus.MAPPING_INTEGRITY_ERROR.value == "MAPPING_INTEGRITY_ERROR"
    assert InfrastructureStatus.COMPLETED.value == "COMPLETED"


def test_versioned_records_forbid_unknown_fields_and_serialize_deterministically() -> None:
    timestamp = datetime(2026, 9, 24, tzinfo=timezone.utc)
    request = RawRequestRecord(
        query_id="Q-1",
        request={"query": "test"},
        timestamp_utc=timestamp,
        runtime_lock_sha256="a" * 64,
        request_sha256="b" * 64,
    )
    response = RawResponseRecord(
        query_id="Q-1",
        transport_status=200,
        response={"results": []},
        timestamp_utc=timestamp,
        latency_ms=12.5,
        response_sha256="c" * 64,
    )
    evidence = RetrievedEvidence(
        rank=1,
        mesa_chunk_id="M-1",
        source_chunk_id="S-1",
        text="evidence",
    )
    artifact = ArtifactReference(path="raw/Q-1.json", sha256="d" * 64)

    assert request.schema_version == "1.0"
    assert response.schema_version == "1.0"
    assert evidence.schema_version == "1.0"
    assert artifact.schema_version == "1.0"
    assert request.model_dump_json() == request.model_dump_json()

    with pytest.raises(ValidationError):
        RawRequestRecord(
            query_id="Q-1",
            request={},
            timestamp_utc=timestamp,
            runtime_lock_sha256="a" * 64,
            request_sha256="b" * 64,
            oracle_answer="forbidden",
        )
