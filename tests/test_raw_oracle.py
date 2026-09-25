from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.artifacts import (
    AnswerExecutionCapture,
    ArtifactOrderError,
    ImmutableArtifactError,
    RunArtifactStore,
)
from harness.oracle import audit_oracle_surfaces, write_oracle_audit


RUN_ID = "RUN-20260924T120000Z-test"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path: Path) -> RunArtifactStore:
    result = RunArtifactStore(tmp_path / RUN_ID, RUN_ID)
    result.initialize()
    return result


def _seal_clean_oracle_audit(store: RunArtifactStore) -> None:
    store.persist_oracle_audit(
        audit_oracle_surfaces({"request": {"query": "normal", "top_k": 5}})
    )


def test_run_layout_separates_raw_and_scored_lanes(store: RunArtifactStore) -> None:
    assert store.raw_retrieval_dir.is_dir()
    assert store.raw_answers_dir.is_dir()
    assert store.scored_retrieval_dir.is_dir()
    assert store.scored_answers_dir.is_dir()


def test_retrieval_raw_is_hashed_sealed_and_precedes_score(
    store: RunArtifactStore,
) -> None:
    raw_path = store.persist_raw_retrieval(
        query_id="Q-1",
        request={"query": "test", "top_k": 5},
        response={"results": [{"chunk_id": "M-1"}]},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=12.5,
        runtime_lock_sha256="a" * 64,
    )
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    sidecar = raw_path.with_suffix(raw_path.suffix + ".SHA256")
    expected_artifact_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()

    assert payload["query_id"] == "Q-1"
    assert payload["request"]["request_sha256"] == hashlib.sha256(
        b'{"query":"test","top_k":5}'
    ).hexdigest()
    assert payload["response"]["response_sha256"] == hashlib.sha256(
        b'{"results":[{"chunk_id":"M-1"}]}'
    ).hexdigest()
    assert sidecar.read_text(encoding="utf-8").split()[0] == expected_artifact_hash

    _seal_clean_oracle_audit(store)
    scored = store.persist_scored(
        lane="retrieval", query_id="Q-1", score={"status": "HIT"}
    )
    scored_payload = json.loads(scored.read_text(encoding="utf-8"))
    assert scored_payload["raw_artifact_sha256"] == expected_artifact_hash


def test_scoring_before_raw_or_after_raw_mutation_fails_closed(
    store: RunArtifactStore,
) -> None:
    _seal_clean_oracle_audit(store)
    with pytest.raises(ArtifactOrderError):
        store.persist_scored(
            lane="retrieval", query_id="Q-missing", score={"status": "MISS"}
        )

    raw_path = store.persist_raw_retrieval(
        query_id="Q-2",
        request={"query": "test"},
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=1.0,
        runtime_lock_sha256="a" * 64,
    )
    raw_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ImmutableArtifactError):
        store.persist_scored(
            lane="retrieval", query_id="Q-2", score={"status": "MISS"}
        )


def test_existing_historical_style_directory_cannot_be_initialized(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    (run_dir / "historical.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ImmutableArtifactError):
        RunArtifactStore(run_dir, RUN_ID).initialize()


def test_answer_capture_preserves_exact_opaque_context(store: RunArtifactStore) -> None:
    context = {
        "opaque_contract_version": "WAIT_FOR_MESA_PHASE_10",
        "items": [{"id": "M-1", "visible_text": "exact text"}],
    }
    capture = AnswerExecutionCapture.from_context(
        query_id="Q-3",
        timestamp_utc=NOW,
        exact_model_visible_context=context,
        context_evidence_ids=["M-1"],
        system_prompt="Use only context.",
        user_prompt="Question",
        provider="provider",
        model="model",
        request_parameters={"temperature": 0},
        raw_response={"answer": "response"},
        parsed_response={"answer": "response", "evidence_chunk_ids": ["M-1"]},
        context_contract_version="WAIT_FOR_MESA_PHASE_10",
    )
    path = store.persist_raw_answer(capture)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["exact_model_visible_context"] == context
    assert payload["context_sha256"] == hashlib.sha256(
        json.dumps(
            context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    _seal_clean_oracle_audit(store)
    store.persist_scored(lane="answers", query_id="Q-3", score={"status": "PASS"})


def test_oracle_audit_recurses_through_fields_prompts_and_context(
    tmp_path: Path,
) -> None:
    clean = audit_oracle_surfaces(
        {
            "retrieval_request": {"query": "normal question", "top_k": 5},
            "system_prompt": "Answer only from supplied context.",
            "context": [{"chunk_id": "M-1", "text": "public source"}],
        }
    )
    leaked = audit_oracle_surfaces(
        {
            "retrieval_request": {
                "query": "normal question",
                "required_facts": ["secret fact"],
            },
            "system_prompt": "Expected PASS label: PASS",
            "context": [{"gold_evidence_ids": ["S-1"]}],
        }
    )
    output = tmp_path / "oracle-leakage-audit.json"
    write_oracle_audit(leaked, output)
    serialized = output.read_text(encoding="utf-8")

    assert clean["status"] == "PASS"
    assert leaked["status"] == "FAIL"
    assert len(leaked["findings"]) == 3
    assert "secret fact" not in serialized
    assert "S-1" not in serialized


def test_raw_writer_preserves_leaked_request_for_audit_but_never_scores_it(
    store: RunArtifactStore,
) -> None:
    request = {"query": "normal", "qrels": ["oracle"]}
    raw = store.persist_raw_retrieval(
        query_id="Q-4",
        request=request,
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=1.0,
        runtime_lock_sha256="a" * 64,
    )
    audit = audit_oracle_surfaces({"request": request})
    store.persist_oracle_audit(audit)

    assert raw.is_file()
    assert audit["status"] == "FAIL"
    with pytest.raises(ArtifactOrderError, match="oracle audit"):
        store.persist_scored(
            lane="retrieval",
            query_id="Q-4",
            score={"status": "MISS"},
        )
