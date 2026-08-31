"""
Deterministic Answer Grader for Profile B.
Evaluates final grounded answers and negative abstention (Doc 17, Doc 33).
"""

import re
from harness.models import GroundTruthItem, AnswerResponse, AnswerScore
from harness.identity import IdentityMap
from harness.normalizer import normalize_text, turkish_casefold

def score_answer(
    gt: GroundTruthItem,
    answer_obj: AnswerResponse,
    retrieved_chunk_ids: list[str],
    identity_map: IdentityMap
) -> AnswerScore:
    """Score final answer deterministically."""
    reasons = []
    
    # 1. Normalize retrieved chunk IDs to source IDs
    normalized_retrieved = {identity_map.resolve_source_chunk_id(cid) for cid in retrieved_chunk_ids}
    
    # 2. Normalize cited chunk IDs to source IDs
    normalized_cited = {identity_map.resolve_source_chunk_id(cid) for cid in answer_obj.evidence_chunk_ids if cid}
    
    # Check NO_ANSWER queries
    if not gt.is_answerable or gt.query_class == "NO_ANSWER":
        # Rule: insufficient_evidence=true AND answer contains 'YETERSİZ KANIT'
        ans_norm = turkish_casefold(normalize_text(answer_obj.answer))
        marker_norm = turkish_casefold("YETERSİZ KANIT")
        
        has_abstention_marker = marker_norm in ans_norm
        flag_set = answer_obj.insufficient_evidence is True
        no_fabricated_evidence = len(normalized_cited) == 0 or normalized_cited.issubset(normalized_retrieved)
        
        if flag_set and has_abstention_marker and no_fabricated_evidence:
            return AnswerScore(
                query_id=gt.query_id,
                is_answerable=False,
                status="PASS",
                reasons=["Correct abstention with required marker"],
                grounded_pass=True,
                evidence_supported=True,
                facts_satisfied=True,
                forbidden_claims_absent=True
            )
        else:
            if not flag_set:
                reasons.append("insufficient_evidence flag not set to true for unanswerable question")
            if not has_abstention_marker:
                reasons.append("Answer missing canonical YETERSİZ KANIT abstention marker")
            if not no_fabricated_evidence:
                reasons.append("Fabricated evidence IDs cited on unanswerable question")
            return AnswerScore(
                query_id=gt.query_id,
                is_answerable=False,
                status="FAIL",
                reasons=reasons,
                grounded_pass=False,
                evidence_supported=False,
                facts_satisfied=False,
                forbidden_claims_absent=True
            )

    # 3. Answerable query grading
    # Rule 1: insufficient_evidence must be False
    if answer_obj.insufficient_evidence is True:
        return AnswerScore(
            query_id=gt.query_id,
            is_answerable=True,
            status="FAIL",
            reasons=["Model incorrectly abstained on answerable question"],
            grounded_pass=False,
            evidence_supported=False,
            facts_satisfied=False,
            forbidden_claims_absent=True
        )

    # Rule 2: Cited evidence must be non-empty and subset of retrieved
    if not normalized_cited:
        reasons.append("No evidence chunk IDs cited")
    elif not normalized_cited.issubset(normalized_retrieved):
        fabricated = normalized_cited - normalized_retrieved
        reasons.append(f"Fabricated evidence IDs not in retrieved context: {fabricated}")

    # Rule 3: Cited evidence must cover expected source chunks / evidence groups
    expected_ids = set(gt.expected_source_chunk_ids)
    evidence_supported = False
    if gt.query_class == "RELATIONAL" and gt.evidence_groups:
        covered_groups = set()
        for group in gt.evidence_groups:
            if set(group.acceptable_source_chunk_ids).intersection(normalized_cited):
                covered_groups.add(group.group_id)
        if len(covered_groups) == len(gt.evidence_groups):
            evidence_supported = True
        else:
            reasons.append(f"Cited evidence covers only {len(covered_groups)}/{len(gt.evidence_groups)} required groups")
    else:
        if expected_ids.intersection(normalized_cited):
            evidence_supported = True
        else:
            reasons.append("Cited evidence does not intersect required expected_source_chunk_ids")

    # Rule 4: Answer text must satisfy required fact patterns / acceptable patterns
    ans_text_norm = turkish_casefold(normalize_text(answer_obj.answer))
    facts_satisfied = False
    
    if gt.acceptable_answer_patterns:
        matched_any = False
        for pat in gt.acceptable_answer_patterns:
            pat_norm = turkish_casefold(normalize_text(pat))
            if pat_norm in ans_text_norm or re.search(re.escape(pat_norm), ans_text_norm):
                matched_any = True
                break
        facts_satisfied = matched_any
        if not facts_satisfied:
            reasons.append("Answer does not match acceptable answer patterns")
    else:
        facts_satisfied = True

    # Rule 5: Forbidden claims must not be present
    forbidden_absent = True
    for forb in gt.forbidden_claims:
        forb_norm = turkish_casefold(normalize_text(forb))
        if forb_norm in ans_text_norm:
            forbidden_absent = False
            reasons.append(f"Answer contains forbidden claim: {forb}")
            break

    is_pass = (
        len(normalized_cited) > 0 and
        normalized_cited.issubset(normalized_retrieved) and
        evidence_supported and
        facts_satisfied and
        forbidden_absent
    )

    return AnswerScore(
        query_id=gt.query_id,
        is_answerable=True,
        status="PASS" if is_pass else "FAIL",
        reasons=reasons if not is_pass else ["Answer valid, grounded, and verified against evidence"],
        grounded_pass=is_pass,
        evidence_supported=evidence_supported,
        facts_satisfied=facts_satisfied,
        forbidden_claims_absent=forbidden_absent
    )
