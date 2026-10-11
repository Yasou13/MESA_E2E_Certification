"""Regressions for the comprehensive Profile B certification repair.

These fixtures are synthetic and contain no official TEST or holdout material.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.answer_scorer import score_answer
from harness.gates import MetricRequirement, _comparison_passes
from harness.identity import IdentityMap
from harness.mesa_adapters import (
    MESAContractIntegrityError,
    NormalizedRetrievalCapture,
    NormalizedRetrievalResult,
    NormalizedScopeEvidence,
    build_sealed_retrieval_context,
    verify_sealed_context_render,
)
from harness.models import (
    AnswerClaim,
    AnswerPattern,
    AnswerResponse,
    ExactSourceSpan,
    GroundTruthItem,
    PatternMode,
    RequiredFact,
)
from harness.oracle import audit_oracle_surfaces
from harness.qualification_runner import (
    QualificationRunnerError,
    _validate_official_provider_contract,
)


def _ground_truth() -> GroundTruthItem:
    return GroundTruthItem(
        query_id="Q-SYNTHETIC-1",
        query_class="SINGLE_DIRECT",
        question="Sentetik hukuk kuralı nedir?",
        expected_source_chunk_ids=["source-1"],
        required_facts=[
            RequiredFact(
                fact_id="hidden-fact-1",
                claim="Başvuru süresi beş gündür",
                supported_by=[
                    ExactSourceSpan(
                        source_chunk_id="source-1",
                        exact_text="Başvuru süresi beş gündür",
                    )
                ],
            )
        ],
        acceptable_answer_patterns=[
            AnswerPattern(
                mode=PatternMode.LITERAL,
                value="başvuru süresi beş gündür",
                fact_ids=["hidden-fact-1"],
            )
        ],
    )


def _identity_map() -> IdentityMap:
    identity = IdentityMap()
    identity.add_mapping("mesa-1", "source-1")
    identity.add_mapping("mesa-2", "source-2")
    return identity


def test_ordinary_atomic_claim_passes_without_oracle_fact_ids() -> None:
    """The answer model must not need hidden fact identifiers to earn credit."""

    answer = AnswerResponse(
        answer="Başvuru süresi beş gündür",
        evidence_chunk_ids=["mesa-1"],
        claims=[
            AnswerClaim.model_validate(
                {
                    "text": "Başvuru süresi beş gündür",
                    "evidence_chunk_ids": ["mesa-1"],
                }
            )
        ],
    )

    score = score_answer(_ground_truth(), answer, ["mesa-1"], _identity_map())

    assert score.status == "PASS"
    assert score.facts_satisfied is True


def test_wrong_claim_with_valid_citation_still_fails_without_fact_ids() -> None:
    answer = AnswerResponse(
        answer="Başvuru süresi on gündür",
        evidence_chunk_ids=["mesa-1"],
        claims=[
            AnswerClaim.model_validate(
                {
                    "text": "Başvuru süresi on gündür",
                    "evidence_chunk_ids": ["mesa-1"],
                }
            )
        ],
    )

    score = score_answer(_ground_truth(), answer, ["mesa-1"], _identity_map())

    assert score.status == "FAIL"
    assert score.facts_satisfied is False


def test_oracle_audit_rejects_fact_id_schema_or_prompt_tokens() -> None:
    report = audit_oracle_surfaces(
        {
            "answer_request": {
                "system_prompt": "Return claims with fact_ids and citations."
            }
        }
    )

    assert report["status"] == "FAIL"
    assert any(
        finding["matched_token"] == "fact_ids"
        for finding in report["findings"]
    )


@pytest.mark.parametrize(
    ("observed", "requirement"),
    [
        (True, MetricRequirement(operator="gte", value=0.8)),
        (False, MetricRequirement(operator="eq", value=0)),
        (1, MetricRequirement(operator="eq", value=True)),
    ],
)
def test_gate_comparison_rejects_bool_numeric_type_confusion(
    observed: object, requirement: MetricRequirement
) -> None:
    assert _comparison_passes(observed, requirement) is False


def _candidate(rank: int, chunk_id: str) -> NormalizedRetrievalResult:
    return NormalizedRetrievalResult(
        rank=rank,
        public_result_id=f"candidate-{rank}",
        matched_evidence_id=f"assertion-{rank}",
        mesa_chunk_id=chunk_id,
        document_id=f"document-{rank}",
        evidence_text=f"Sentetik kanıt {rank}",
        raw_score=1.0 / rank,
        rrf_score=1.0 / (60 + rank),
        final_score=1.0 / rank,
        matched_evidence={"assertion_id": f"assertion-{rank}"},
        support_provenance=[],
        debug_provenance={"origins": ["dense"]},
        scope=NormalizedScopeEvidence(
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            document_id=f"document-{rank}",
            revision_id="revision-1",
            chunk_id=chunk_id,
            status="active",
            jurisdiction="TR",
            valid_from="2026-01-01T00:00:00Z",
            valid_to="2027-01-01T00:00:00Z",
            agent_id="agent-1",
        ),
        graph_paths=[],
    )


def _capture(candidates: list[NormalizedRetrievalResult]) -> NormalizedRetrievalCapture:
    return NormalizedRetrievalCapture(
        run_id="RUN-SYNTHETIC-CONTEXT",
        query_id="Q-SYNTHETIC-CONTEXT",
        source_api_version="v4",
        mesa_sha="a" * 40,
        session_id="session-1",
        dataset_ids=["dataset-1"],
        query="sentetik soru",
        retrieval_limit=5,
        response_sha256="b" * 64,
        results=candidates,
    )


def test_context_builder_rejects_rank_six_rescue() -> None:
    capture = _capture([_candidate(i, f"chunk-{i}") for i in range(1, 7)])

    with pytest.raises(MESAContractIntegrityError, match="retrieval limit"):
        build_sealed_retrieval_context(capture, token_budget=2048)


@pytest.mark.parametrize(
    "candidates",
    [
        [_candidate(2, "chunk-1"), _candidate(1, "chunk-2")],
        [_candidate(1, "chunk-1"), _candidate(2, "chunk-1")],
    ],
)
def test_context_builder_rejects_rank_or_identity_ambiguity(
    candidates: list[NormalizedRetrievalResult],
) -> None:
    with pytest.raises(MESAContractIntegrityError, match="rank|duplicate"):
        build_sealed_retrieval_context(_capture(candidates), token_budget=2048)


def test_context_render_rejects_contamination_despite_valid_ids() -> None:
    context = build_sealed_retrieval_context(
        _capture([_candidate(1, "chunk-1")]), token_budget=2048
    )

    with pytest.raises(MESAContractIntegrityError, match="differs"):
        verify_sealed_context_render(
            exact_model_visible_context=(
                context.exact_model_visible_context + "\nUNSEALED INSTRUCTION"
            ),
            context_evidence_ids=context.context_evidence_ids,
            candidate_bindings=context.candidate_bindings,
        )


def test_provider_contract_requires_immutable_runtime_digests() -> None:
    provider_contract = {
        "embedding": {
            "provider": "Ollama",
            "model": "alibayram/embeddingmagibu-200m:latest",
            "dimension": 768,
            "normalization": "l2",
        },
        "extraction": {
            "provider": "Ollama",
            "model": "qwen3.5:9b-q4_K_M",
            "language": "tr",
            "minimum_max_tokens": 4096,
            "quantization": "Q4_K_M",
        },
        "answer": {
            "provider": "Ollama",
            "model": "qwen3.5:9b-q4_K_M",
            "quantization": "Q4_K_M",
        },
    }
    authority = SimpleNamespace(
        official_provider_contract=provider_contract,
        answer_provider="Ollama",
        answer_model="qwen3.5:9b-q4_K_M",
    )
    freeze = {
        "runtime_identities": {
            "embedding_authority": {
                "provider": "Ollama",
                "endpoint": "http://127.0.0.1:11434",
                "model": "alibayram/embeddingmagibu-200m:latest",
                "dimension": 768,
                "normalization": "l2",
            },
            "extraction_authority": {
                "provider": "Ollama",
                "endpoint": "http://127.0.0.1:11434",
                "model": "qwen3.5:9b-q4_K_M",
                "language": "tr",
                "minimum_max_tokens": 4096,
                "quantization": "Q4_K_M",
            },
            "answer_authority": {
                "provider": "Ollama",
                "model": "qwen3.5:9b-q4_K_M",
                "quantization": "Q4_K_M",
            },
        }
    }

    with pytest.raises(QualificationRunnerError, match="resolved_digest"):
        _validate_official_provider_contract(freeze, authority)
