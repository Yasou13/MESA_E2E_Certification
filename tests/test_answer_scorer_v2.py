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


def test_all_required_facts_must_be_satisfied(identity_map: IdentityMap) -> None:
    gt = GroundTruthItem(
        query_id="Q-1",
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
    response = _answer("Birinci olgu", ["f1"], ["M-1"])

    score = score_answer(gt, response, ["M-1", "M-2"], identity_map)

    assert score.status == "FAIL"
    assert score.facts_satisfied is False
    assert any("f2" in reason for reason in score.reasons)


def test_regex_and_literal_modes_are_distinct(identity_map: IdentityMap) -> None:
    base = dict(
        query_id="Q-2",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Hâkim hukuku uygular")],
    )
    response = _answer("Hâkim somut olayda hukuku uygular", ["f1"], ["M-1"])
    regex_gt = GroundTruthItem(
        **base,
        acceptable_answer_patterns=[
            _pattern("f1", r"hâkim.*hukuku", PatternMode.REGEX)
        ],
    )
    literal_gt = GroundTruthItem(
        **base,
        acceptable_answer_patterns=[
            _pattern("f1", r"hâkim.*hukuku", PatternMode.LITERAL)
        ],
    )

    # Regex recognizes the required phrase, but does not prove appended material.
    from harness.answer_scorer import _pattern_matches
    assert _pattern_matches(regex_gt.acceptable_answer_patterns[0], response.answer)
    assert not _pattern_matches(literal_gt.acceptable_answer_patterns[0], response.answer)
    assert score_answer(regex_gt, response, ["M-1"], identity_map).status != "PASS"
    assert score_answer(literal_gt, response, ["M-1"], identity_map).status == "FAIL"


@pytest.mark.parametrize(
    ("pattern", "expected_status"),
    [
        (
            AnswerPattern(
                mode=PatternMode.ALL_OF,
                values=["hâkim", "hukuku"],
                fact_ids=["f1"],
            ),
            "PASS",
        ),
        (
            AnswerPattern(
                mode=PatternMode.ALL_OF,
                values=["hâkim", "olmayan"],
                fact_ids=["f1"],
            ),
            "FAIL",
        ),
        (
            AnswerPattern(
                mode=PatternMode.ANY_OF,
                values=["yargıç", "hâkim"],
                fact_ids=["f1"],
            ),
            "PASS",
        ),
    ],
)
def test_all_of_and_any_of_modes_are_explicit(
    identity_map: IdentityMap,
    pattern: AnswerPattern,
    expected_status: str,
) -> None:
    text = "Hâkim somut olayda hukuku uygular"
    gt = GroundTruthItem(
        query_id="Q-2B",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", text)],
        acceptable_answer_patterns=[pattern],
    )

    score = score_answer(gt, _answer(text, ["f1"], ["M-1"]), ["M-1"], identity_map)

    assert score.status == expected_status


def test_denial_containing_required_keyword_cannot_pass(
    identity_map: IdentityMap,
) -> None:
    text = "Bu kaynakta dürüstlük kuralı bulunmamaktadır"
    gt = GroundTruthItem(
        query_id="Q-3",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", "Dürüstlük kuralı uygulanır")],
        acceptable_answer_patterns=[_pattern("f1", "dürüstlük")],
    )

    score = score_answer(gt, _answer(text, ["f1"], ["M-1"]), ["M-1"], identity_map)

    assert score.status == "FAIL"
    assert score.facts_satisfied is False


def test_no_answer_requires_exact_marker_and_no_citations(
    identity_map: IdentityMap,
) -> None:
    gt = GroundTruthItem(
        query_id="Q-4",
        query_class="NO_ANSWER",
        question="question",
        is_answerable=False,
    )
    strict = AnswerResponse(answer="YETERSİZ KANIT", insufficient_evidence=True)
    appended = AnswerResponse(
        answer="Ceza 10 yıldır. YETERSİZ KANIT", insufficient_evidence=True
    )
    cited = AnswerResponse(
        answer="YETERSİZ KANIT",
        evidence_chunk_ids=["M-1"],
        insufficient_evidence=True,
    )

    assert score_answer(gt, strict, ["M-1"], identity_map).status == "PASS"
    assert score_answer(gt, appended, ["M-1"], identity_map).status == "FAIL"
    assert score_answer(gt, cited, ["M-1"], identity_map).status == "FAIL"


def test_unsupported_extra_material_is_unresolved(identity_map: IdentityMap) -> None:
    supported = "Dürüstlük kuralı uygulanır"
    gt = GroundTruthItem(
        query_id="Q-5",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", supported)],
        acceptable_answer_patterns=[_pattern("f1", "dürüstlük")],
    )
    response = AnswerResponse(
        answer=f"{supported}. Ayrıca ceza on yıldır",
        evidence_chunk_ids=["M-1"],
        claims=[
            AnswerClaim(
                fact_ids=["f1"], text=supported, evidence_chunk_ids=["M-1"]
            )
        ],
    )

    score = score_answer(gt, response, ["M-1"], identity_map)

    assert score.status == "UNRESOLVED"
    assert any("unstructured material" in reason for reason in score.reasons)


def test_citation_outside_context_forbidden_claim_and_unknown_identity_fail(
    identity_map: IdentityMap,
) -> None:
    text = "Dürüstlük kuralı uygulanır"
    gt = GroundTruthItem(
        query_id="Q-6",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", text)],
        acceptable_answer_patterns=[_pattern("f1", "dürüstlük")],
        forbidden_claims=["ceza on yıldır"],
    )

    outside = _answer(text, ["f1"], ["M-2"])
    forbidden = _answer(f"{text}; ceza on yıldır", ["f1"], ["M-1"])
    unknown = _answer(text, ["f1"], ["M-UNKNOWN"])

    assert score_answer(gt, outside, ["M-1"], identity_map).status == "FAIL"
    assert score_answer(gt, forbidden, ["M-1"], identity_map).status == "FAIL"
    assert (
        score_answer(gt, unknown, ["M-1"], identity_map).status
        == "MAPPING_INTEGRITY_ERROR"
    )


def test_missing_fact_pattern_is_unresolved_not_invented_confidence(
    identity_map: IdentityMap,
) -> None:
    text = "Dürüstlük kuralı uygulanır"
    gt = GroundTruthItem(
        query_id="Q-7",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        required_facts=[_fact("f1", "S-1", text)],
        acceptable_answer_patterns=["dürüstlük"],
    )

    score = score_answer(gt, _answer(text, ["f1"], ["M-1"]), ["M-1"], identity_map)

    assert score.status == "UNRESOLVED"
