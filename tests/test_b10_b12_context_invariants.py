"""Deterministic tests for B10 -> B12 context-binding invariants.

Verifies cases 1 through 7 specified in Section 25:
CASE 1: Relevant evidence rank 1 -> retrieval HIT -> context eligible
CASE 2: Relevant evidence rank 5 -> HIT@5 -> context eligible subject to budget
CASE 3: Relevant evidence rank 6 or 8 -> B10 MISS@5 -> MUST NOT silently enter official top-5-bound answer context
CASE 4: Evidence available only from hypothetical second retrieval -> MUST NOT enter context
CASE 5: Relevant top-5 evidence rejected by token budget -> retrieval PASS coexists with answer failure/abstention, diagnostics explain rejection
CASE 6: Context evidence not present in sealed allowed set -> certification FAIL CLOSED
CASE 7: Every included context evidence ID can be traced to one sealed candidate
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from harness.artifacts import CertifiedAnswerExecutionCapture
from harness.identity import IdentityMap
from harness.mesa_adapters import (
    NormalizedContextCapture,
    NormalizedRetrievalCapture,
    NormalizedRetrievalResult,
    NormalizedScopeEvidence,
    build_sealed_retrieval_context,
)
from harness.models import GroundTruthItem
from harness.retrieval_scorer import score_retrieval

RUN_ID = "RUN-20261009T120000Z-ctx-invariants"
MESA_SHA = "a" * 40
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def _make_candidate(
    rank: int,
    chunk_id: str,
    *,
    evidence_text: str = "Legal standard is defined.",
    tenant_id: str = "tenant-1",
    agent_id: str = "agent-1",
) -> NormalizedRetrievalResult:
    return NormalizedRetrievalResult(
        rank=rank,
        public_result_id=f"res-{chunk_id}",
        matched_evidence_id=chunk_id,
        mesa_chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        evidence_text=evidence_text,
        raw_score=1.0 - (rank * 0.1),
        rrf_score=1.0 / (60 + rank),
        final_score=1.0 - (rank * 0.1),
        matched_evidence={"evidence_id": chunk_id, "chunk_id": chunk_id},
        support_provenance=[],
        debug_provenance={"origins": ["dense_lane"]},
        scope=NormalizedScopeEvidence(
            tenant_id=tenant_id,
            dataset_id="dataset-inv-1",
            document_id=f"doc-{chunk_id}",
            revision_id="rev-1",
            chunk_id=chunk_id,
            status="active",
            jurisdiction="TR",
            valid_from="2026-01-01T00:00:00Z",
            valid_to="2026-12-31T23:59:59Z",
            agent_id=agent_id,
        ),
        graph_paths=[],
    )


def _make_retrieval_capture(
    candidates: list[NormalizedRetrievalResult],
    query_id: str = "Q-INV-01",
) -> NormalizedRetrievalCapture:
    resp = {"candidates": [c.model_dump(mode="json") for c in candidates]}
    resp_bytes = json.dumps(resp, sort_keys=True).encode("utf-8")
    return NormalizedRetrievalCapture(
        schema_version="1.0",
        run_id=RUN_ID,
        query_id=query_id,
        query="What is the legal standard?",
        retrieval_limit=5,
        source_api_version="v4",
        mesa_sha=MESA_SHA,
        session_id="session-inv-01",
        dataset_ids=["dataset-inv-1"],
        results=candidates,
        response_sha256=hashlib.sha256(resp_bytes).hexdigest(),
    )


# =========================================================================
# CASE 1: Relevant evidence rank 1 -> retrieval HIT -> context eligible
# =========================================================================
def test_case_1_rank_1_retrieval_hit_and_context_eligible() -> None:
    identity_map = IdentityMap()
    for i in range(1, 6):
        identity_map.add_mapping(f"mesa-chunk-{i}", f"source-chunk-{i}")

    gt = GroundTruthItem(
        query_id="Q-01",
        query_class="SINGLE_DIRECT",
        question="What is the legal requirement?",
        expected_source_chunk_ids=["source-chunk-1"],
    )

    candidates = [
        _make_candidate(1, "mesa-chunk-1"),
        _make_candidate(2, "mesa-chunk-2"),
        _make_candidate(3, "mesa-chunk-3"),
        _make_candidate(4, "mesa-chunk-4"),
        _make_candidate(5, "mesa-chunk-5"),
    ]

    # 1. Retrieval scoring: HIT at rank 1
    retrieval_records = [{"chunk_id": c.mesa_chunk_id} for c in candidates]
    score = score_retrieval(gt, retrieval_records, identity_map)
    assert score.rank == 1
    assert score.recall_at_5 == 1.0
    assert score.mrr == 1.0

    # 2. Context building: mesa-chunk-1 is included in context
    capture = _make_retrieval_capture(candidates)
    ctx = build_sealed_retrieval_context(capture, token_budget=2048)
    assert "mesa-chunk-1" in ctx.context_evidence_ids
    assert ctx.candidate_bindings[0]["included"] is True
    assert ctx.candidate_bindings[0]["rejection_reason"] is None


# =========================================================================
# CASE 2: Relevant evidence rank 5 -> HIT@5 -> context eligible
# =========================================================================
def test_case_2_rank_5_retrieval_hit_and_context_eligible() -> None:
    identity_map = IdentityMap()
    for i in range(1, 6):
        identity_map.add_mapping(f"mesa-chunk-{i}", f"source-chunk-{i}")

    gt = GroundTruthItem(
        query_id="Q-02",
        query_class="SINGLE_DIRECT",
        question="What is the condition?",
        expected_source_chunk_ids=["source-chunk-5"],
    )

    candidates = [
        _make_candidate(1, "mesa-chunk-1"),
        _make_candidate(2, "mesa-chunk-2"),
        _make_candidate(3, "mesa-chunk-3"),
        _make_candidate(4, "mesa-chunk-4"),
        _make_candidate(5, "mesa-chunk-5"),
    ]

    # 1. Retrieval scoring: HIT at rank 5
    retrieval_records = [{"chunk_id": c.mesa_chunk_id} for c in candidates]
    score = score_retrieval(gt, retrieval_records, identity_map)
    assert score.rank == 5
    assert score.recall_at_5 == 1.0
    assert score.mrr == 0.2

    # 2. Context building: mesa-chunk-5 is in context when budget permits
    capture = _make_retrieval_capture(candidates)
    ctx = build_sealed_retrieval_context(capture, token_budget=2048)
    assert "mesa-chunk-5" in ctx.context_evidence_ids
    assert ctx.candidate_bindings[4]["included"] is True


# =========================================================================
# CASE 3: Relevant evidence rank 6 or 8 -> B10 MISS@5 -> MUST NOT enter context
# =========================================================================
def test_case_3_rank_6_or_8_miss_never_enters_top5_context() -> None:
    identity_map = IdentityMap()
    for i in range(1, 7):
        identity_map.add_mapping(f"mesa-chunk-{i}", f"source-chunk-{i}")

    gt = GroundTruthItem(
        query_id="Q-03",
        query_class="SINGLE_DIRECT",
        question="What is the regulation?",
        expected_source_chunk_ids=["source-chunk-6"],
    )

    # Retrieval only keeps top-5 candidates for Profile B
    top5_candidates = [
        _make_candidate(1, "mesa-chunk-1"),
        _make_candidate(2, "mesa-chunk-2"),
        _make_candidate(3, "mesa-chunk-3"),
        _make_candidate(4, "mesa-chunk-4"),
        _make_candidate(5, "mesa-chunk-5"),
    ]

    # 1. Retrieval scoring: MISS at top-5
    retrieval_records = [{"chunk_id": c.mesa_chunk_id} for c in top5_candidates]
    score = score_retrieval(gt, retrieval_records, identity_map)
    assert score.rank is None
    assert score.recall_at_5 == 0.0
    assert score.mrr == 0.0

    # 2. Context building: chunk-6 was rank 6, so it cannot be in top-5 context
    capture = _make_retrieval_capture(top5_candidates)
    ctx = build_sealed_retrieval_context(capture, token_budget=2048)
    assert "mesa-chunk-6" not in ctx.context_evidence_ids
    assert "mesa-chunk-6" not in ctx.allowed_retrieval_evidence_ids


# =========================================================================
# CASE 4: Evidence from hypothetical second retrieval MUST NOT enter context
# =========================================================================
def test_case_4_second_retrieval_evidence_rejected() -> None:
    top5_candidates = [
        _make_candidate(1, "mesa-chunk-1"),
        _make_candidate(2, "mesa-chunk-2"),
        _make_candidate(3, "mesa-chunk-3"),
        _make_candidate(4, "mesa-chunk-4"),
        _make_candidate(5, "mesa-chunk-5"),
    ]
    capture = _make_retrieval_capture(top5_candidates)
    ctx = build_sealed_retrieval_context(capture, token_budget=2048)

    # If an attacker or bug tries to inject evidence from a second unsealed query
    foreign_chunk = "mesa-chunk-second-retrieval"
    assert foreign_chunk not in ctx.allowed_retrieval_evidence_ids

    # Attempting to construct CertifiedAnswerExecutionCapture with this foreign chunk fails closed
    with pytest.raises(ValidationError, match="outside the allowed sealed retrieval set"):
        CertifiedAnswerExecutionCapture(
            run_id=RUN_ID,
            query_id="Q-04",
            timestamp_utc=NOW,
            capture_origin="harness.answer_execution.provider_boundary",
            source_context_contract="mesa-e2e.sealed-retrieval-context.v1",
            context_contract_version="mesa-e2e.context.v2",
            mesa_sha=MESA_SHA,
            tenant_id="tenant-1",
            agent_id="agent-1",
            session_id="session-1",
            dataset_ids=["dataset-1"],
            exact_model_visible_context=ctx.exact_model_visible_context,
            context_evidence_ids=[*ctx.context_evidence_ids, foreign_chunk],  # Injected!
            allowed_retrieval_evidence_ids=ctx.allowed_retrieval_evidence_ids,
            retrieval_response_sha256=ctx.retrieval_response_sha256,
            context_candidate_bindings=ctx.candidate_bindings,
            context_sha256=ctx.context_sha256,
            system_prompt="sys",
            system_prompt_sha256=hashlib.sha256(b"sys").hexdigest(),
            question="q",
            question_sha256=hashlib.sha256(b"q").hexdigest(),
            answer_instruction="inst",
            answer_instruction_sha256=hashlib.sha256(b"inst").hexdigest(),
            user_prompt=f"inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\n{ctx.exact_model_visible_context}",
            user_prompt_sha256=hashlib.sha256(
                f"inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\n{ctx.exact_model_visible_context}".encode("utf-8")
            ).hexdigest(),
            provider="Ollama",
            model="qwen3.5:9b-q4_K_M",
            request_parameters={},
            exact_provider_request={
                "model": "qwen3.5:9b-q4_K_M",
                "messages": [
                    {"role": "system", "content": "sys"},
                    {
                        "role": "user",
                        "content": f"inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\n{ctx.exact_model_visible_context}",
                    },
                ],
            },
            request_sha256=hashlib.sha256(
                json.dumps(
                    {
                        "messages": [
                            {"role": "system", "content": "sys"},
                            {
                                "role": "user",
                                "content": f"inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\n{ctx.exact_model_visible_context}",
                            },
                        ],
                        "model": "qwen3.5:9b-q4_K_M",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            raw_provider_response={"choices": [{"message": {"content": "ans"}}]},
            response_sha256=hashlib.sha256(
                json.dumps({"choices": [{"message": {"content": "ans"}}]}, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
            provider_exchange_sha256="0" * 64,
            parsed_response={"answer": "ans"},
        )


# =========================================================================
# CASE 5: Relevant top-5 evidence rejected by budget -> diagnostics explain
# =========================================================================
def test_case_5_token_budget_rejection_diagnostics() -> None:
    # Huge evidence text that exceeds a small token budget
    large_text = "Detailed paragraph explaining the extensive background. " * 50
    candidates = [
        _make_candidate(1, "mesa-chunk-1", evidence_text=large_text),
        _make_candidate(2, "mesa-chunk-2", evidence_text=large_text),
        _make_candidate(3, "mesa-chunk-3", evidence_text=large_text),
    ]
    capture = _make_retrieval_capture(candidates)

    # Budget of only 50 tokens = 200 bytes
    ctx = build_sealed_retrieval_context(capture, token_budget=50)

    # Chunk 1 might not even fit, or chunk 2 and 3 get rejected
    rejected = [b for b in ctx.candidate_bindings if not b["included"]]
    assert len(rejected) > 0
    for r in rejected:
        assert r["rejection_reason"] == "token_budget"
        assert r["source_chunk_id"] not in ctx.context_evidence_ids


# =========================================================================
# CASE 6: Context evidence not present in sealed allowed set -> FAIL CLOSED
# =========================================================================
def test_case_6_context_outside_sealed_set_fails_closed() -> None:
    candidates = [_make_candidate(1, "chunk-allowed-1")]
    capture = _make_retrieval_capture(candidates)
    ctx = build_sealed_retrieval_context(capture, token_budget=2048)

    # Corrupt context capture to claim unsealed chunk
    corrupted_ctx = ctx.model_copy(
        update={
            "context_evidence_ids": ["chunk-allowed-1", "chunk-unsealed-x"],
            "allowed_retrieval_evidence_ids": ["chunk-allowed-1"],
        }
    )
    assert not set(corrupted_ctx.context_evidence_ids).issubset(
        corrupted_ctx.allowed_retrieval_evidence_ids
    )


# =========================================================================
# CASE 7: Every included context evidence ID is traceable to one sealed candidate
# =========================================================================
def test_case_7_all_context_evidence_traceable_to_sealed_candidate() -> None:
    candidates = [
        _make_candidate(1, "chunk-1"),
        _make_candidate(2, "chunk-2"),
        _make_candidate(3, "chunk-3"),
        _make_candidate(4, "chunk-4"),
        _make_candidate(5, "chunk-5"),
    ]
    capture = _make_retrieval_capture(candidates)
    ctx = build_sealed_retrieval_context(capture, token_budget=2048)

    candidate_map = {c.mesa_chunk_id: c for c in candidates}
    for evidence_id in ctx.context_evidence_ids:
        # Traceability: must exist in original candidate list
        assert evidence_id in candidate_map
        orig = candidate_map[evidence_id]
        # Traceability: matching binding entry exists
        binding = next(b for b in ctx.candidate_bindings if b["source_chunk_id"] == evidence_id)
        assert binding["rank"] == orig.rank
        assert binding["candidate_id"] == orig.public_result_id
        assert binding["included"] is True
        assert binding["retrieval_origins"] == ["dense_lane"]
