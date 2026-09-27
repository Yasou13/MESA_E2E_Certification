from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from harness.answer_execution import AnswerExecutionError, execute_answer_and_persist
from harness.artifacts import CertifiedAnswerExecutionCapture, RunArtifactStore
from harness.mesa_adapters import (
    MESAContractBlocker,
    MESAContractIntegrityError,
    normalize_context_response,
    normalize_search_response,
    require_phase7_scope_contract,
    require_phase8_9_graph_contract,
)


RUN_ID = "RUN-adapter"
MESA_SHA = "1" * 40
NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _assertion(assertion_id: str, chunk_id: str, **updates):
    value = {
        "assertion_id": assertion_id,
        "tenant_id": "tenant-a",
        "dataset_id": "dataset-a",
        "document_id": "document-a",
        "revision_id": "revision-a",
        "chunk_id": chunk_id,
        "status": "ACTIVE",
        "jurisdiction": "TR",
        "valid_from": "2026-01-01",
        "valid_to": "",
        "evidence_span": "exact evidence",
    }
    value.update(updates)
    return value


def _result(*, assertion_id="assertion-a", chunk_id="chunk-a", graph=False):
    matched = _assertion(assertion_id, chunk_id)
    support = []
    debug = {"origins": ["vector"], "lane_ranks": {"vector": 1}, "raw_scores": {"vector": 0.1}}
    if graph:
        support = [_assertion("assertion-support", "chunk-support")]
        debug = {
            **debug,
            "origins": ["graph"],
            "graph_paths": [
                {
                    "assertion_ids": ["assertion-support", assertion_id],
                    "entity_ids": ["entity-1", "entity-2", "entity-3"],
                    "edge_directions": ["forward", "reverse"],
                    "predicates": ["supports", "governs"],
                    "seed_id": "entity-1",
                    "score": 0.7,
                }
            ],
        }
    return {
        "entity": {"canonical_name": "Rule"},
        "candidate_id": assertion_id,
        "evidence_id": assertion_id,
        "assertion_id": assertion_id,
        "source_chunk_id": chunk_id,
        "document_id": "document-a",
        "evidence_span": "exact evidence",
        "raw_score": 0.1,
        "rrf_score": 0.2,
        "legal_factor": 1.0,
        "final_score": 0.2,
        "provenance": [matched, *support],
        "matched_assertions": [matched],
        "supporting_assertions": support,
        "retrieval_provenance": debug,
    }


def _capture(results=None):
    return normalize_search_response(
        run_id=RUN_ID,
        query_id="Q-1",
        request={
            "session_id": "session-a",
            "dataset_ids": ["dataset-a"],
            "query": "question",
            "limit": 5,
        },
        response={
            "session_id": "session-a",
            "dataset_ids": ["dataset-a"],
            "results": [_result()] if results is None else results,
        },
        api_version="v4",
        mesa_sha=MESA_SHA,
    )


def test_phase1_normalizes_only_first_class_matched_evidence() -> None:
    capture = _capture([_result(graph=True)])
    result = capture.results[0]
    assert result.rank == 1
    assert result.mesa_chunk_id == "chunk-a"
    assert result.matched_evidence_id == "assertion-a"
    assert [item["assertion_id"] for item in result.support_provenance] == [
        "assertion-support"
    ]


def test_phase1_rejects_entity_wide_provenance_false_hit() -> None:
    result = _result()
    result["provenance"].append(_assertion("unlabelled", "wrong-chunk"))
    with pytest.raises(MESAContractIntegrityError, match="matched plus support"):
        _capture([result])


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda rows: rows.append(dict(rows[0])), "duplicate ranked"),
        (lambda rows: rows[0].update(source_chunk_id=""), "source_chunk_id"),
        (lambda rows: rows[0].update(evidence_id="different"), "conflicting"),
    ],
)
def test_phase1_rejects_duplicate_or_malformed_identity(mutation, match) -> None:
    rows = [_result()]
    mutation(rows)
    with pytest.raises(MESAContractIntegrityError, match=match):
        _capture(rows)


def test_phase1_empty_result_and_serialization_are_deterministic() -> None:
    first = _capture([])
    second = _capture([])
    assert first.model_dump_json() == second.model_dump_json()
    assert first.results == []


def test_phase1_rejects_source_version_and_sha_mismatch() -> None:
    with pytest.raises(MESAContractIntegrityError, match="api_version"):
        normalize_search_response(
            run_id=RUN_ID,
            query_id="Q-1",
            request={"session_id": "s", "query": "q"},
            response={"session_id": "s", "dataset_ids": ["d"], "results": []},
            api_version="v5",
            mesa_sha=MESA_SHA,
        )


def test_phase7_missing_native_candidate_audit_is_explicit_blocker() -> None:
    with pytest.raises(MESAContractBlocker) as exc:
        require_phase7_scope_contract(_capture())
    assert exc.value.blocker_id == "WAIT_FOR_MESA_PHASE_7"
    assert "candidate.agent_id" in exc.value.missing_capabilities
    assert "candidate.pre_rank_scope_audit_id" in exc.value.missing_capabilities


def test_phase8_9_validates_path_but_blocks_missing_stable_pair_contract() -> None:
    capture = _capture([_result(graph=True)])
    assert capture.results[0].graph_paths[0].edge_directions == ["forward", "reverse"]
    with pytest.raises(MESAContractBlocker) as exc:
        require_phase8_9_graph_contract(capture)
    assert "graph_path_id" in exc.value.missing_capabilities
    assert "native_graph_on_off_execution_identity" in exc.value.missing_capabilities


def test_graph_duplicate_path_cannot_amplify_support() -> None:
    result = _result(graph=True)
    path = dict(result["retrieval_provenance"]["graph_paths"][0])
    result["retrieval_provenance"]["graph_paths"].append(path)
    with pytest.raises(MESAContractIntegrityError, match="duplicate graph path"):
        _capture([result])


def _context():
    return normalize_context_response(
        run_id=RUN_ID,
        query_id="Q-1",
        response={
            "tenant_id": "tenant-a",
            "agent_id": "agent-a",
            "session_id": "session-a",
            "dataset_ids": ["dataset-a"],
            "context": "first\nsecond",
            "canonical_memories": [
                {"source_chunk_id": "chunk-1", "evidence_id": "assertion-1"},
                {"source_chunk_id": "chunk-2", "evidence_id": "assertion-2"},
            ],
            "estimated_token_count": 2,
            "mutations": [],
        },
        api_version="v4",
        mesa_sha=MESA_SHA,
    )


class _Transport:
    provider_name = "openai_compatible"

    def complete(self, request_payload):
        return {
            "id": "provider-request-1",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": "answer",
                                "evidence_chunk_ids": ["chunk-1"],
                                "insufficient_evidence": False,
                                "claims": [
                                    {
                                        "fact_ids": ["F1"],
                                        "text": "answer",
                                        "evidence_chunk_ids": ["chunk-1"],
                                    }
                                ],
                            }
                        )
                    }
                }
            ],
        }


def test_phase10_exact_provider_boundary_capture_is_sealed(tmp_path) -> None:
    store = RunArtifactStore(tmp_path / RUN_ID, RUN_ID)
    store.initialize()
    capture = execute_answer_and_persist(
        store=store,
        context=_context(),
        question="question",
        system_prompt="system",
        answer_instruction="use only context",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0, "max_tokens": 512},
        transport=_Transport(),
        timestamp_utc=NOW,
    )
    raw_path = store.raw_answers_dir / "Q-1.json"
    persisted = json.loads(raw_path.read_text())
    assert persisted["schema_version"] == "2.0"
    assert persisted["exact_model_visible_context"] == "first\nsecond"
    assert persisted["context_evidence_ids"] == ["chunk-1", "chunk-2"]
    assert CertifiedAnswerExecutionCapture.model_validate(persisted)
    store._verify_seal(raw_path)


def test_phase10_rejects_oracle_fields_before_provider_call(tmp_path) -> None:
    store = RunArtifactStore(tmp_path / RUN_ID, RUN_ID)
    store.initialize()
    with pytest.raises(AnswerExecutionError, match="oracle"):
        execute_answer_and_persist(
            store=store,
            context=_context(),
            question="question",
            system_prompt="system",
            answer_instruction="instruction",
            model="openai/gpt-oss-20b",
            request_parameters={"required_facts": ["secret"]},
            transport=_Transport(),
            timestamp_utc=NOW,
        )


def test_phase10_hash_tampering_is_rejected(tmp_path) -> None:
    store = RunArtifactStore(tmp_path / RUN_ID, RUN_ID)
    store.initialize()
    capture = execute_answer_and_persist(
        store=store,
        context=_context(),
        question="question",
        system_prompt="system",
        answer_instruction="instruction",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0},
        transport=_Transport(),
        timestamp_utc=NOW,
    )
    payload = capture.model_dump(mode="json")
    payload["exact_model_visible_context"] = "reconstructed later"
    with pytest.raises(ValueError, match="context_sha256"):
        CertifiedAnswerExecutionCapture.model_validate(payload)
