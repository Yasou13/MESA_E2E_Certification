"""Fail-closed deterministic answer scorer for Profile B."""

from __future__ import annotations

import re

from harness.identity import IdentityMap, UnknownIdentityError
from harness.models import (
    AnswerPattern,
    AnswerResponse,
    AnswerScore,
    GroundTruthItem,
    PatternMode,
)
from harness.normalizer import get_abstention_marker, normalize_text, turkish_casefold


DENIAL_WORDS = frozenset(
    {
        "değil",
        "değildir",
        "yok",
        "yoktur",
        "bulunmaz",
        "bulunmamaktadır",
        "öngörülmemiştir",
        "öngörülmez",
        "uygulanmaz",
        "uygulanamaz",
        "geçersizdir",
    }
)

DENIAL_PHRASES = (
    "geçerli değildir",
    "söz konusu değildir",
    "yer almamaktadır",
    "cevap verilemez",
    "bilgi verilemez",
    "yanıt veremiyorum",
    "kanıt yoktur",
    "yetersiz kanıt",
)

STOPWORDS = frozenset(
    {
        "ve", "veya", "ile", "için", "bir", "bu", "ise", "de", "da", "göre",
        "olarak", "gibi", "ancak", "fakat", "şu", "o", "ki", "daha", "en",
        "ayrıca", "her", "tüm", "bütün", "vardır", "ise", "ya", "ne",
        "hakkında", "olmak", "olan", "olduğu", "buna", "bunun", "şekilde",
        "somut", "olayda", "olay", "ilgili", "gereğince", "uyarınca",
        "belirtilmiştir", "öngörülmüştür", "düzenlenmiştir", "yer", "alır",
    }
)


def _normalized(text: str) -> str:
    return turkish_casefold(normalize_text(text))


def _stringify_context(context: Any) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return context
    if isinstance(context, (list, tuple, set)):
        return " ".join(_stringify_context(x) for x in context)
    if isinstance(context, dict):
        return " ".join(_stringify_context(v) for v in context.values())
    return str(context)


def _contains_denial(text: str, target: str = "") -> bool:
    normalized = _normalized(text)
    norm_target = _normalized(target) if target else ""
    for phrase in DENIAL_PHRASES:
        norm_phrase = _normalized(phrase)
        if norm_phrase in normalized and norm_phrase not in norm_target:
            return True
    for word in DENIAL_WORDS:
        norm_word = _normalized(word)
        if norm_word not in norm_target:
            if re.search(r"(?:\b|_)" + re.escape(norm_word) + r"(?:\b|_)", normalized):
                return True
    return False


def _pattern_matches(pattern: AnswerPattern, text: str) -> bool:
    target_str = ""
    if pattern.mode in {PatternMode.LITERAL, PatternMode.REGEX}:
        target_str = pattern.value or ""
    elif pattern.values:
        target_str = " ".join(pattern.values)

    if _contains_denial(text, target=target_str):
        return False
    normalized_text = _normalized(text)
    if pattern.mode is PatternMode.LITERAL:
        return _normalized(pattern.value or "") in normalized_text
    if pattern.mode is PatternMode.REGEX:
        normalized_pattern = _normalized(pattern.value or "")
        return re.search(normalized_pattern, normalized_text) is not None
    normalized_values = [_normalized(value) for value in pattern.values]
    if pattern.mode is PatternMode.ALL_OF:
        return all(value in normalized_text for value in normalized_values)
    return any(value in normalized_text for value in normalized_values)


def _has_unstructured_material(answer: str, claim_texts: list[str]) -> bool:
    remainder = _normalized(answer)
    for claim_text in sorted(claim_texts, key=len, reverse=True):
        normalized_claim = _normalized(claim_text)
        if normalized_claim not in remainder:
            return True
        remainder = remainder.replace(normalized_claim, " ", 1)
    return bool(re.sub(r"[\W_]+", "", remainder, flags=re.UNICODE))


def _mapping_error(gt: GroundTruthItem, error: UnknownIdentityError) -> AnswerScore:
    return AnswerScore(
        query_id=gt.query_id,
        is_answerable=gt.is_answerable,
        status="MAPPING_INTEGRITY_ERROR",
        reasons=[str(error)],
        grounded_pass=False,
        evidence_supported=False,
        facts_satisfied=False,
        forbidden_claims_absent=False,
        unsupported_material_claim_count=0,
    )


def score_answer(
    gt: GroundTruthItem,
    answer_obj: AnswerResponse,
    retrieved_chunk_ids: list[str],
    identity_map: IdentityMap,
    *,
    exact_model_visible_context: Any = None,
) -> AnswerScore:
    """Score an answer without converting semantic ambiguity into PASS."""
    try:
        normalized_retrieved = {
            identity_map.resolve_source_chunk_id(chunk_id)
            for chunk_id in retrieved_chunk_ids
        }
        normalized_cited = {
            identity_map.resolve_source_chunk_id(chunk_id)
            for chunk_id in answer_obj.evidence_chunk_ids
            if chunk_id
        }
        normalized_claim_evidence = [
            {
                identity_map.resolve_source_chunk_id(chunk_id)
                for chunk_id in claim.evidence_chunk_ids
            }
            for claim in answer_obj.claims
        ]
    except UnknownIdentityError as exc:
        return _mapping_error(gt, exc)

    reasons: list[str] = []
    unresolved: list[str] = []

    if not gt.is_answerable or gt.query_class == "NO_ANSWER":
        exact_marker = _normalized(answer_obj.answer) == _normalized(
            get_abstention_marker()
        )
        flag_set = answer_obj.insufficient_evidence is True
        no_citations = not normalized_cited and not answer_obj.claims
        if flag_set and exact_marker and no_citations:
            return AnswerScore(
                query_id=gt.query_id,
                is_answerable=False,
                status="PASS",
                reasons=["Exact canonical abstention without appended claims"],
                grounded_pass=True,
                evidence_supported=True,
                facts_satisfied=True,
                forbidden_claims_absent=True,
            )
        if not flag_set:
            reasons.append("insufficient_evidence flag is not true")
        if not exact_marker:
            reasons.append("answer is not exactly the canonical abstention marker")
        if not no_citations:
            reasons.append("NO_ANSWER response contains evidence citations or claims")
        return AnswerScore(
            query_id=gt.query_id,
            is_answerable=False,
            status="FAIL",
            reasons=reasons,
            grounded_pass=False,
            evidence_supported=False,
            facts_satisfied=False,
            forbidden_claims_absent=True,
        )

    if answer_obj.insufficient_evidence:
        return AnswerScore(
            query_id=gt.query_id,
            is_answerable=True,
            status="FAIL",
            reasons=["model incorrectly abstained on an answerable question"],
            grounded_pass=False,
            evidence_supported=False,
            facts_satisfied=False,
            forbidden_claims_absent=True,
        )

    citation_subset = bool(normalized_cited) and normalized_cited.issubset(
        normalized_retrieved
    )
    if not normalized_cited:
        reasons.append("no evidence chunk IDs cited")
    elif not citation_subset:
        fabricated = sorted(normalized_cited - normalized_retrieved)
        reasons.append(f"evidence IDs outside retrieved context: {fabricated}")

    if gt.query_class == "RELATIONAL" and gt.evidence_groups:
        covered_groups = {
            group.group_id
            for group in gt.evidence_groups
            if set(group.acceptable_source_chunk_ids).intersection(normalized_cited)
        }
        evidence_supported = len(covered_groups) == len(gt.evidence_groups)
        if not evidence_supported:
            reasons.append(
                "cited evidence covers only "
                f"{len(covered_groups)}/{len(gt.evidence_groups)} required groups"
            )
    else:
        expected_ids = set(gt.expected_source_chunk_ids)
        evidence_supported = bool(expected_ids.intersection(normalized_cited))
        if not evidence_supported:
            reasons.append(
                "cited evidence does not intersect expected_source_chunk_ids"
            )

    answer_normalized = _normalized(answer_obj.answer)
    forbidden_absent = True
    for forbidden in gt.forbidden_claims:
        if _normalized(forbidden) in answer_normalized:
            forbidden_absent = False
            reasons.append(f"answer contains forbidden claim: {forbidden}")

    required_by_id = {fact.fact_id: fact for fact in gt.required_facts}
    if not required_by_id:
        unresolved.append("answerable item has no source-linked required_facts")
    if not answer_obj.claims:
        unresolved.append("answer has no structured material claims")

    unknown_claim_facts = sorted(
        {
            fact_id
            for claim in answer_obj.claims
            for fact_id in claim.fact_ids
            if fact_id not in required_by_id
        }
    )
    if unknown_claim_facts:
        unresolved.append(f"claims reference unknown fact IDs: {unknown_claim_facts}")

    all_claim_evidence_supported = True
    for claim, claim_evidence in zip(
        answer_obj.claims, normalized_claim_evidence, strict=True
    ):
        if not claim_evidence.issubset(normalized_retrieved):
            reasons.append(
                f"claim evidence is outside retrieved context: {claim.fact_ids}"
            )
            all_claim_evidence_supported = False
        if not claim_evidence.issubset(normalized_cited):
            reasons.append(
                f"claim evidence is absent from answer citations: {claim.fact_ids}"
            )
            all_claim_evidence_supported = False

    satisfied_fact_ids: set[str] = set()
    supported_claim_indexes: set[int] = set()
    for fact_id, fact in required_by_id.items():
        patterns = [
            pattern
            for pattern in gt.acceptable_answer_patterns
            if fact_id in pattern.fact_ids
        ]
        if not patterns:
            unresolved.append(f"required fact {fact_id} has no explicit pattern")
            continue
        fact_source_ids = {span.source_chunk_id for span in fact.supported_by}
        if not fact_source_ids:
            unresolved.append(f"required fact {fact_id} has no frozen evidence link")
            continue
        candidate_indexes = [
            index
            for index, claim in enumerate(answer_obj.claims)
            if fact_id in claim.fact_ids
        ]
        if not candidate_indexes:
            reasons.append(f"required fact {fact_id} is missing")
            continue
        fact_passed = False
        for index in candidate_indexes:
            claim = answer_obj.claims[index]
            if not fact_source_ids.intersection(normalized_claim_evidence[index]):
                continue
            if not any(_pattern_matches(pattern, claim.text) for pattern in patterns):
                continue

            # Check for unsupported additional material in the claim itself
            # Vocabulary overlap cannot prove a legal proposition. Only a
            # complete source-linked claim/span is deterministic support here;
            # paraphrases remain unresolved pending an approved evaluator.
            def proposition(text: str) -> str:
                return _normalized(text).strip().rstrip(".!?; ")

            supported_texts = {proposition(fact.claim)} | {
                proposition(span.exact_text) for span in fact.supported_by
                if span.source_chunk_id in normalized_claim_evidence[index]
            }
            if proposition(claim.text) not in supported_texts:
                unresolved.append(
                    f"claim {claim.fact_ids} contains unsupported material or unresolved paraphrase"
                )
                continue

            fact_passed = True
            supported_claim_indexes.add(index)
        if fact_passed:
            satisfied_fact_ids.add(fact_id)
        else:
            reasons.append(
                f"required fact {fact_id} is denied, unsupported, or unmatched"
            )

    for index in range(len(answer_obj.claims)):
        if index not in supported_claim_indexes:
            unresolved.append(f"claim {index} contains unsupported material")

    facts_satisfied = bool(required_by_id) and satisfied_fact_ids == set(
        required_by_id
    )
    if answer_obj.claims and _has_unstructured_material(
        answer_obj.answer, [claim.text for claim in answer_obj.claims]
    ):
        unresolved.append("answer contains unstructured material outside claims")

    evidence_supported = (
        evidence_supported and citation_subset and all_claim_evidence_supported
    )
    hard_failure = bool(reasons)
    if hard_failure:
        status = "FAIL"
    elif unresolved:
        status = "UNRESOLVED"
    elif evidence_supported and facts_satisfied and forbidden_absent:
        status = "PASS"
    else:
        status = "FAIL"
        reasons.append("grounded PASS invariants were not satisfied")

    is_pass = status == "PASS"
    unsupported_claim_count = len([u for u in unresolved if "contains unsupported material" in u])
    return AnswerScore(
        query_id=gt.query_id,
        is_answerable=True,
        status=status,
        reasons=(reasons + unresolved)
        if not is_pass
        else ["all source-linked facts and material claims verified"],
        grounded_pass=is_pass,
        evidence_supported=evidence_supported,
        facts_satisfied=facts_satisfied,
        forbidden_claims_absent=forbidden_absent,
        unsupported_material_claim_count=unsupported_claim_count,
    )
