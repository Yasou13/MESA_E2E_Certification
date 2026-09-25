from __future__ import annotations

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


@pytest.fixture
def identity_map() -> IdentityMap:
    mapping = IdentityMap()
    mapping.add_mapping("M-1", "S-1")
    mapping.add_mapping("M-2", "S-2")
    return mapping


def _fact(fact_id: str, source_id: str, claim: str) -> RequiredFact:
    return RequiredFact(
        fact_id=fact_id,
        claim=claim,
        supported_by=[
            ExactSourceSpan(source_chunk_id=source_id, exact_text=claim)
        ],
    )


def _pattern(
    fact_id: str, value: str, mode: PatternMode = PatternMode.LITERAL
) -> AnswerPattern:
    return AnswerPattern(mode=mode, value=value, fact_ids=[fact_id])


def _answer(
    text: str, fact_ids: list[str], evidence_ids: list[str]
) -> AnswerResponse:
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


# Test 1: correct required fact -> PASS
def test_c4_01_correct_required_fact_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-1",
        query_class="SINGLE_DIRECT",
        question="Ceza süresi ne kadardır?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıldır", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "PASS"


# Test 2: required fact negated with değildir -> FAIL
def test_c4_02_required_fact_negated_degildir_fail(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-2",
        query_class="SINGLE_DIRECT",
        question="Ceza süresi ne kadardır?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıl değildir", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "FAIL"


# Test 3: required fact negated with another form (yoktur, uygulanmaz, etc.) -> FAIL
@pytest.mark.parametrize(
    "negated_text",
    [
        "Ceza 5 yıl yoktur",
        "Bu hüküm uygulanmaz",
        "Söz konusu değildir",
        "Geçerli değildir",
        "Öngörülmemiştir",
        "Kusur bulunmaz",
    ],
)
def test_c4_03_required_fact_negated_variations_fail(
    identity_map: IdentityMap, negated_text: str
) -> None:
    gt = GroundTruthItem(
        query_id="Q-3",
        query_class="SINGLE_DIRECT",
        question="Hüküm nasıldır?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "hüküm geçerlidir")],
        acceptable_answer_patterns=[
            AnswerPattern(
                mode=PatternMode.ANY_OF,
                values=["ceza 5 yıl", "hüküm", "kusur"],
                fact_ids=["f1"],
            )
        ],
    )
    resp = _answer(negated_text, ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "FAIL"


# Test 4: one of two required facts missing -> FAIL
def test_c4_04_one_of_two_required_facts_missing_fail(
    identity_map: IdentityMap,
) -> None:
    gt = GroundTruthItem(
        query_id="Q-4",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1", "S-2"],
        required_facts=[
            _fact("f1", "S-1", "Birinci olgu"),
            _fact("f2", "S-2", "İkinci olgu"),
        ],
        acceptable_answer_patterns=[
            _pattern("f1", "birinci olgu"),
            _pattern("f2", "ikinci olgu"),
        ],
    )
    resp = _answer("Birinci olgu gerçekleşmiştir", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1", "M-2"], identity_map)
    assert score.status == "FAIL"
    assert score.facts_satisfied is False


# Test 5: correct fact + unsupported material hallucination -> FAIL or UNRESOLVED (cannot be PASS)
def test_c4_05_correct_fact_plus_unsupported_hallucination(
    identity_map: IdentityMap,
) -> None:
    gt = GroundTruthItem(
        query_id="Q-5",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer(
        "Ceza 5 yıldır ve ayrıca 100 milyon TL tazminat vardır",
        ["f1"],
        ["M-1"],
    )
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# Test 6: fabricated evidence ID -> FAIL
def test_c4_06_fabricated_evidence_id_fail(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-6",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    # Citing M-2 when only M-1 was retrieved
    resp = _answer("Ceza 5 yıldır", ["f1"], ["M-2"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "FAIL"


# Test 7: citation outside model-visible context -> FAIL
def test_c4_07_citation_outside_model_visible_context_fail(
    identity_map: IdentityMap,
) -> None:
    gt = GroundTruthItem(
        query_id="Q-7",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
    )
    resp = _answer("Ceza 5 yıldır", ["f1"], ["M-1"])
    # Retrieved chunk is M-2, so cited M-1 is outside model-visible retrieved context
    score = score_answer(gt, resp, ["M-2"], identity_map)
    assert score.status == "FAIL"


# Test 8: forbidden claim -> FAIL
def test_c4_08_forbidden_claim_fail(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-8",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Ceza 5 yıldır")],
        acceptable_answer_patterns=[_pattern("f1", "ceza 5 yıl")],
        forbidden_claims=["ceza 10 yıldır"],
    )
    resp = _answer("Ceza 5 yıldır ancak ceza 10 yıldır da denir", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "FAIL"


# Test 9: strict NO_ANSWER exact form -> PASS
def test_c4_09_strict_no_answer_exact_form_pass(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-9",
        query_class="NO_ANSWER",
        question="question",
        is_answerable=False,
    )
    resp = AnswerResponse(answer="YETERSİZ KANIT", insufficient_evidence=True)
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "PASS"


# Test 10: substantive text + NO_ANSWER marker -> FAIL
def test_c4_10_substantive_text_plus_no_answer_marker_fail(
    identity_map: IdentityMap,
) -> None:
    gt = GroundTruthItem(
        query_id="Q-10",
        query_class="NO_ANSWER",
        question="question",
        is_answerable=False,
    )
    resp = AnswerResponse(
        answer="Ceza 5 yıldır. YETERSİZ KANIT", insufficient_evidence=True
    )
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "FAIL"


# Test 11: regex pattern works as regex only when schema marks it regex
def test_c4_11_regex_works_only_when_marked_regex(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-11",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Hakim somut olayda hukuku uygular")],
        acceptable_answer_patterns=[
            _pattern("f1", r"hakim.*hukuku", PatternMode.REGEX)
        ],
    )
    resp = _answer("Hakim somut olayda hukuku uygular", ["f1"], ["M-1"])
    score = score_answer(gt, resp, ["M-1"], identity_map)
    assert score.status == "PASS"


# Test 12: literal metacharacters remain literal when schema says literal
def test_c4_12_literal_metacharacters_remain_literal(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-12",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Madde 5(a) [fıkra 1]* uygulanır")],
        acceptable_answer_patterns=[
            _pattern("f1", "5(a) [fıkra 1]*", PatternMode.LITERAL)
        ],
    )
    resp_match = _answer("Madde 5(a) [fıkra 1]* uygulanır", ["f1"], ["M-1"])
    score_match = score_answer(gt, resp_match, ["M-1"], identity_map)
    assert score_match.status == "PASS"

    # If it were interpreted as regex, 5a would match 5(a) with regex groupings/quantifiers
    resp_no_match = _answer("Madde 5a fıkra 1 uygulanır", ["f1"], ["M-1"])
    score_no_match = score_answer(gt, resp_no_match, ["M-1"], identity_map)
    assert score_no_match.status == "FAIL"
