"""Regression test suite for F4: Answer scoring fails closed on unsupported material claims."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from harness.answer_scorer import score_answer
from harness.identity import IdentityMap
from harness.models import (
    AnswerClaim,
    AnswerPattern,
    AnswerResponse,
    ExactSourceSpan,
    GroundTruthItem,
    PatternMode,
    RequiredFact,
)
from harness.transaction import CertificationTransaction


@pytest.fixture
def identity_map() -> IdentityMap:
    mapping = IdentityMap()
    mapping.add_mapping("M-1", "S-1")
    mapping.add_mapping("M-2", "S-2")
    return mapping


def _fact(fact_id: str, source_id: str, claim: str, extra_spans: list[ExactSourceSpan] | None = None) -> RequiredFact:
    spans = [ExactSourceSpan(source_chunk_id=source_id, exact_text=claim)]
    if extra_spans:
        spans.extend(extra_spans)
    return RequiredFact(
        fact_id=fact_id,
        claim=claim,
        supported_by=spans,
    )


def _pattern(fact_id: str, value: str, mode: PatternMode = PatternMode.LITERAL) -> AnswerPattern:
    return AnswerPattern(mode=mode, value=value, fact_ids=[fact_id])


def _answer(text: str, fact_ids: list[str], evidence_ids: list[str]) -> AnswerResponse:
    return AnswerResponse(
        answer=text,
        evidence_chunk_ids=evidence_ids,
        insufficient_evidence=False,
        claims=[
            AnswerClaim(
                fact_ids=fact_ids,
                text=text,
                evidence_chunk_ids=evidence_ids,
            )
        ],
    )


# 1. gold fact present + 1 unsupported material token -> FAIL or UNRESOLVED (not PASS)
def test_1_gold_fact_plus_one_unsupported_token_not_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-1",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    # 1 unsupported word: "sürgün"
    resp = _answer("Ceza 5 yıldır sürgün", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# 2. gold fact present + unsupported monetary value -> FAIL or UNRESOLVED
def test_2_gold_fact_plus_unsupported_monetary_not_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-2",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    # Unsupported monetary value: 500 TL
    resp = _answer("Ceza 5 yıldır 500 TL", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# 3. gold fact present + unsupported date -> FAIL or UNRESOLVED
def test_3_gold_fact_plus_unsupported_date_not_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-3",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    # Unsupported date: 2026
    resp = _answer("Ceza 5 yıldır 2026", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# 4. gold fact present + unsupported entity -> FAIL or UNRESOLVED
def test_4_gold_fact_plus_unsupported_entity_not_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-4",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    # Unsupported entity: Ahmet
    resp = _answer("Ceza 5 yıldır Ahmet", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# 5. gold fact present + negated meaning -> FAIL
def test_5_gold_fact_plus_negated_meaning_fail(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-5",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıl değildir", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "FAIL"


# 6. gold fact present + completely grounded extra text -> PASS
def test_6_gold_fact_plus_completely_grounded_extra_text_pass(identity_map: IdentityMap) -> None:
    # Source span contains full sentence
    gt = GroundTruthItem(
        query_id="Q-6",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[
            _fact(
                "f1",
                "S-1",
                "Ceza 5 yıldır ve hâkim takdir eder",
            )
        ],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıldır ve hâkim takdir eder", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "PASS"


# 7. exact gold fact alone -> PASS
def test_7_exact_gold_fact_alone_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-7",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıldır", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "PASS"


# 8. NO_ANSWER query + correct abstention -> PASS
def test_8_no_answer_correct_abstention_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-8",
        query_class="NO_ANSWER",
        question="Bilinmeyen soru?",
        is_answerable=False,
    )
    resp = AnswerResponse(
        answer="YETERSİZ KANIT",
        insufficient_evidence=True,
    )
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "PASS"


# 9. NO_ANSWER query + hallucinated answer -> FAIL
def test_9_no_answer_hallucinated_answer_fail(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-9",
        query_class="NO_ANSWER",
        question="Bilinmeyen soru?",
        is_answerable=False,
    )
    resp = AnswerResponse(
        answer="Ceza 5 yıldır",
        evidence_chunk_ids=["M-1"],
        insufficient_evidence=False,
        claims=[AnswerClaim(fact_ids=["f1"], text="Ceza 5 yıldır", evidence_chunk_ids=["M-1"])],
    )
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "FAIL"


# 10. unanswerable query + non-empty evidence but no valid answer -> abstention PASS
def test_10_unanswerable_with_non_empty_retrieval_correct_abstention_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-10",
        query_class="NO_ANSWER",
        question="Kanıtı olmayan soru?",
        is_answerable=False,
    )
    resp = AnswerResponse(
        answer="YETERSİZ KANIT",
        insufficient_evidence=True,
        evidence_chunk_ids=[],
    )
    score = score_answer(gt, resp, ["M-1", "M-2"], identity_map)
    assert score.status == "PASS"


# 11. ungrounded claim where evidence is completely empty -> FAIL
def test_11_ungrounded_claim_empty_evidence_fail(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-11",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıldır", ["f1"], ["M-1"])
    # Empty retrieved evidence context
    score = score_answer(gt, resp, [], identity_map)
    assert score.status == "FAIL"


# 12. determinism test: repeated scoring of same unsupported claim produces identical score
def test_12_determinism_repeated_scoring_identical(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-12",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıldır sürgün 2026", ["f1"], ["M-1"])
    results = [score_answer(gt, resp, ["M-1"], identity_map).model_dump(mode="json") for _ in range(10)]
    for r in results[1:]:
        assert r == results[0]


# 13. B12 gate reflects unsupported claims in unsupported_material_claim_rate
def test_13_b12_gate_reflects_unsupported_claims(tmp_path: Path) -> None:
    from harness.artifacts import RunArtifactStore
    from harness.transaction import CertificationTransaction
    from harness.models import VerdictStatus

    run_id = "RUN-20260925T170000Z-f4test"
    run_dir = tmp_path / run_id
    tx = CertificationTransaction(run_id, run_dir)
    tx.execute_bootstrap()

    # Create dummy freeze
    from tests.test_f1_raw_oracle_scoring_binding import _make_freeze
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, run_id)
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    # Persist raw answer with unsupported claim
    def build_raw(d: Path):
        store = RunArtifactStore(d, run_id)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc="2026-09-25T12:00:00Z",
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
        from harness.artifacts import AnswerExecutionCapture
        capture = AnswerExecutionCapture.from_context(
            query_id="Q-1",
            timestamp_utc="2026-09-25T12:00:00Z",
            exact_model_visible_context="Ceza 5 yıldır",
            context_evidence_ids=["M-1"],
            system_prompt="sys",
            user_prompt="usr",
            provider="test",
            model="test",
            request_parameters={},
            raw_response={},
            parsed_response={"answer": "Ceza 5 yıldır sürgün", "evidence_chunk_ids": ["M-1"]},
            context_contract_version="1.0",
        )
        store.persist_raw_answer(capture)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()

    gt_dict = {
        "query_id": "Q-1",
        "query_class": "SINGLE_DIRECT",
        "question": "Ceza nedir?",
        "expected_source_chunk_ids": ["S-1"],
        "required_facts": [{"fact_id": "f1", "claim": "Ceza 5 yıldır", "supported_by": [{"source_chunk_id": "S-1", "exact_text": "Ceza 5 yıldır"}]}],
        "acceptable_answer_patterns": [{"mode": "literal", "value": "ceza 5 yıl", "fact_ids": ["f1"]}],
        "is_answerable": True,
    }

    # Custom scoring fn using real score_answer
    imap = IdentityMap()
    imap.add_mapping("M-1", "S-1")
    def custom_scorer(raw_payload: dict):
        if "parsed_response" in raw_payload:
            ans = AnswerResponse(
                answer=raw_payload["parsed_response"]["answer"],
                evidence_chunk_ids=raw_payload["parsed_response"]["evidence_chunk_ids"],
                claims=[AnswerClaim(fact_ids=["f1"], text=raw_payload["parsed_response"]["answer"], evidence_chunk_ids=["M-1"])]
            )
            gt_item = GroundTruthItem.model_validate(gt_dict)
            sc = score_answer(gt_item, ans, ["M-1"], imap)
            dumped = sc.model_dump(mode="json")
            dumped["lane"] = "answers"
            return dumped
        else:
            return {"query_id": "Q-1", "status": "PASS", "lane": "retrieval", "recall_at_5": 1.0, "mrr": 1.0}

    tx.execute_scoring(scoring_fn=custom_scorer)
    gate_results = tx.execute_gate_evaluation()
    b12_result = next((g for g in gate_results if g.gate_id == "B12"), None)
    assert b12_result is not None
    # B12 must FAIL because unsupported_material_claim_rate > 0
    assert b12_result.status.value != "PASS"
    assert b12_result.observed.get("unsupported_material_claim_rate", 0) > 0


# 14. non-empty answerable test set with 0 unsupported claims -> B12 PASS
def test_14_non_empty_clean_set_passes_b12(tmp_path: Path) -> None:
    from harness.artifacts import RunArtifactStore
    from harness.transaction import CertificationTransaction

    run_id = "RUN-20260925T170000Z-f4test2"
    run_dir = tmp_path / run_id
    tx = CertificationTransaction(run_id, run_dir)
    tx.execute_bootstrap()

    from tests.test_f1_raw_oracle_scoring_binding import _make_freeze
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, run_id)
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, run_id)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc="2026-09-25T12:00:00Z",
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
        from harness.artifacts import AnswerExecutionCapture
        capture = AnswerExecutionCapture.from_context(
            query_id="Q-1",
            timestamp_utc="2026-09-25T12:00:00Z",
            exact_model_visible_context="Ceza 5 yıldır",
            context_evidence_ids=["M-1"],
            system_prompt="sys",
            user_prompt="usr",
            provider="test",
            model="test",
            request_parameters={},
            raw_response={},
            parsed_response={"answer": "Ceza 5 yıldır", "evidence_chunk_ids": ["M-1"]},
            context_contract_version="1.0",
        )
        store.persist_raw_answer(capture)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()

    gt_dict = {
        "query_id": "Q-1",
        "query_class": "SINGLE_DIRECT",
        "question": "Ceza nedir?",
        "expected_source_chunk_ids": ["S-1"],
        "required_facts": [{"fact_id": "f1", "claim": "Ceza 5 yıldır", "supported_by": [{"source_chunk_id": "S-1", "exact_text": "Ceza 5 yıldır"}]}],
        "acceptable_answer_patterns": [{"mode": "literal", "value": "ceza 5 yıl", "fact_ids": ["f1"]}],
        "is_answerable": True,
    }

    imap = IdentityMap()
    imap.add_mapping("M-1", "S-1")
    def custom_scorer(raw_payload: dict):
        if "parsed_response" in raw_payload:
            ans = AnswerResponse(
                answer=raw_payload["parsed_response"]["answer"],
                evidence_chunk_ids=raw_payload["parsed_response"]["evidence_chunk_ids"],
                claims=[AnswerClaim(fact_ids=["f1"], text=raw_payload["parsed_response"]["answer"], evidence_chunk_ids=["M-1"])]
            )
            gt_item = GroundTruthItem.model_validate(gt_dict)
            sc = score_answer(gt_item, ans, ["M-1"], imap)
            dumped = sc.model_dump(mode="json")
            dumped["lane"] = "answers"
            return dumped
        else:
            return {"query_id": "Q-1", "status": "PASS", "lane": "retrieval", "recall_at_5": 1.0, "mrr": 1.0}

    tx.execute_scoring(scoring_fn=custom_scorer)
    gate_results = tx.execute_gate_evaluation()
    b12_result = next((g for g in gate_results if g.gate_id == "B12"), None)
    assert b12_result is not None
    assert b12_result.status.value == "PASS"
    assert b12_result.observed.get("unsupported_material_claim_rate") == 0
