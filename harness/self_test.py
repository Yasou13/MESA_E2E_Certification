"""
Deterministic 17 Synthetic Self-Tests for Phase H0 Certification Harness.
Adheres strictly to Doc 33 Section 3.
"""

import json
import time
from harness.models import (
    GroundTruthItem, RequiredFact, EvidenceGroup, ExactSourceSpan,
    AnswerResponse
)
from harness.identity import IdentityMap
from harness.normalizer import normalize_text, turkish_casefold, normalize_law_id, normalize_article_id
from harness.retrieval_scorer import score_retrieval
from harness.answer_scorer import score_answer

def run_harness_self_tests() -> dict:
    results = []
    
    # Setup standard IdentityMap
    id_map = IdentityMap()
    id_map.add_mapping("MESA-CHUNK-001", "SRC-CHUNK-A")
    id_map.add_mapping("MESA-CHUNK-002", "SRC-CHUNK-B")
    id_map.add_mapping("MESA-CHUNK-003", "SRC-CHUNK-C")
    id_map.add_mapping("MESA-CHUNK-004", "SRC-CHUNK-D")
    id_map.add_mapping("MESA-CHUNK-005", "SRC-CHUNK-E")
    id_map.add_mapping("MESA-CHUNK-006", "SRC-CHUNK-F")

    # --- Test 1: Direct retrieval hit at rank 1 ---
    gt1 = GroundTruthItem(
        query_id="TEST-01",
        query_class="SINGLE_DIRECT",
        question="Madde 1 nedir?",
        expected_source_chunk_ids=["SRC-CHUNK-A"]
    )
    ret1 = [{"chunk_id": "MESA-CHUNK-001"}, {"chunk_id": "MESA-CHUNK-002"}]
    s1 = score_retrieval(gt1, ret1, id_map)
    assert s1.status == "HIT" and s1.rank == 1 and s1.recall_at_1 == 1.0 and s1.recall_at_5 == 1.0 and s1.mrr == 1.0
    results.append({"case": 1, "name": "direct retrieval hit at rank 1", "status": "PASS"})

    # --- Test 2: Hit exactly at rank 5 ---
    ret2 = [
        {"chunk_id": "MESA-CHUNK-002"}, {"chunk_id": "MESA-CHUNK-003"},
        {"chunk_id": "MESA-CHUNK-004"}, {"chunk_id": "MESA-CHUNK-005"},
        {"chunk_id": "MESA-CHUNK-001"}
    ]
    s2 = score_retrieval(gt1, ret2, id_map)
    assert s2.status == "HIT" and s2.rank == 5 and s2.recall_at_1 == 0.0 and s2.recall_at_5 == 1.0 and abs(s2.mrr - 0.2) < 1e-4
    results.append({"case": 2, "name": "hit exactly at rank 5", "status": "PASS"})

    # --- Test 3: Complete miss ---
    ret3 = [{"chunk_id": "MESA-CHUNK-002"}, {"chunk_id": "MESA-CHUNK-003"}]
    s3 = score_retrieval(gt1, ret3, id_map)
    assert s3.status == "MISS" and s3.rank is None and s3.recall_at_1 == 0.0 and s3.recall_at_5 == 0.0 and s3.mrr == 0.0
    results.append({"case": 3, "name": "complete miss", "status": "PASS"})

    # --- Test 4: Duplicate returned evidence IDs ---
    ret4 = [{"chunk_id": "MESA-CHUNK-001"}, {"chunk_id": "MESA-CHUNK-001"}]
    s4 = score_retrieval(gt1, ret4, id_map)
    assert s4.status == "HIT" and s4.rank == 1 and len(s4.matching_chunk_ids) == 1
    results.append({"case": 4, "name": "duplicate returned evidence IDs", "status": "PASS"})

    # --- Test 5: Equivalent source/MESA chunk identity mapping ---
    id_map_eq = IdentityMap()
    id_map_eq.add_mapping("SRC-DIRECT-001", "SRC-DIRECT-001")
    gt5 = GroundTruthItem(query_id="TEST-05", query_class="SINGLE_DIRECT", question="Test", expected_source_chunk_ids=["SRC-DIRECT-001"])
    ret5 = [{"chunk_id": "SRC-DIRECT-001"}]
    s5 = score_retrieval(gt5, ret5, id_map_eq)
    assert s5.status == "HIT" and s5.rank == 1
    results.append({"case": 5, "name": "equivalent source/MESA chunk identity mapping", "status": "PASS"})

    # --- Test 6: Source chunk ID different from MESA public chunk ID ---
    id_map_diff = IdentityMap()
    id_map_diff.add_mapping("MESA-PUBLIC-999", "SRC-CANONICAL-001")
    gt6 = GroundTruthItem(query_id="TEST-06", query_class="SINGLE_DIRECT", question="Test", expected_source_chunk_ids=["SRC-CANONICAL-001"])
    ret6 = [{"chunk_id": "MESA-PUBLIC-999"}]
    s6 = score_retrieval(gt6, ret6, id_map_diff)
    assert s6.status == "HIT" and s6.matching_chunk_ids == ["SRC-CANONICAL-001"]
    results.append({"case": 6, "name": "source chunk ID different from MESA public chunk ID", "status": "PASS"})

    # --- Test 7: REL query with all evidence groups ---
    gt7 = GroundTruthItem(
        query_id="TEST-07",
        query_class="RELATIONAL",
        question="Relational query",
        evidence_groups=[
            EvidenceGroup(group_id="G1", acceptable_source_chunk_ids=["SRC-CHUNK-A"]),
            EvidenceGroup(group_id="G2", acceptable_source_chunk_ids=["SRC-CHUNK-B"])
        ]
    )
    ret7 = [{"chunk_id": "MESA-CHUNK-001"}, {"chunk_id": "MESA-CHUNK-002"}]
    s7 = score_retrieval(gt7, ret7, id_map)
    assert s7.status == "HIT" and s7.complete_evidence_at_5 == 1.0 and s7.group_coverage_at_5 == 1.0
    results.append({"case": 7, "name": "REL query with all evidence groups", "status": "PASS"})

    # --- Test 8: REL query missing exactly one evidence group ---
    ret8 = [{"chunk_id": "MESA-CHUNK-001"}, {"chunk_id": "MESA-CHUNK-003"}]
    s8 = score_retrieval(gt7, ret8, id_map)
    assert s8.status == "PARTIAL" and s8.complete_evidence_at_5 == 0.0 and s8.group_coverage_at_5 == 0.5
    results.append({"case": 8, "name": "REL query missing exactly one evidence group", "status": "PASS"})

    # --- Test 9: Malformed provenance ---
    ret9 = [{"malformed": "data"}]
    s9 = score_retrieval(gt1, ret9, id_map)
    assert s9.status == "MISS"
    results.append({"case": 9, "name": "malformed provenance", "status": "PASS"})

    # --- Test 10: Infrastructure error distinct from retrieval MISS ---
    s10 = score_retrieval(gt1, [], id_map, is_infrastructure_error=True)
    assert s10.status == "INFRASTRUCTURE_ERROR" and s10.rank is None
    results.append({"case": 10, "name": "infrastructure error distinct from retrieval MISS", "status": "PASS"})

    # --- Test 11: NO_ANSWER correct abstention ---
    gt11 = GroundTruthItem(query_id="TEST-11", query_class="NO_ANSWER", question="Olmayan kanun maddesi?", is_answerable=False)
    ans11 = AnswerResponse(answer="Verilen kaynaklarda bu bilgi bulunmamaktadır. YETERSİZ KANIT.", evidence_chunk_ids=[], insufficient_evidence=True)
    a11 = score_answer(gt11, ans11, ["MESA-CHUNK-001"], id_map)
    assert a11.status == "PASS" and a11.grounded_pass is True
    results.append({"case": 11, "name": "NO_ANSWER correct abstention", "status": "PASS"})

    # --- Test 12: NO_ANSWER hallucinated answer ---
    ans12 = AnswerResponse(answer="Bu kanun maddesine göre ceza 5 yıldır.", evidence_chunk_ids=[], insufficient_evidence=False)
    a12 = score_answer(gt11, ans12, ["MESA-CHUNK-001"], id_map)
    assert a12.status == "FAIL" and a12.grounded_pass is False
    results.append({"case": 12, "name": "NO_ANSWER hallucinated answer", "status": "PASS"})

    # --- Test 13: Correct answer with fabricated evidence ID ---
    gt13 = GroundTruthItem(
        query_id="TEST-13", query_class="SINGLE_DIRECT", question="Soru",
        expected_source_chunk_ids=["SRC-CHUNK-A"], acceptable_answer_patterns=["Doğru Cevap"]
    )
    ans13 = AnswerResponse(answer="Doğru Cevap", evidence_chunk_ids=["MESA-FAKE-999"], insufficient_evidence=False)
    a13 = score_answer(gt13, ans13, ["MESA-CHUNK-001"], id_map)
    assert a13.status == "FAIL" and any("Fabricated" in r for r in a13.reasons)
    results.append({"case": 13, "name": "correct answer with fabricated evidence ID", "status": "PASS"})

    # --- Test 14: Correct wording but unsupported evidence ---
    ans14 = AnswerResponse(answer="Doğru Cevap", evidence_chunk_ids=["MESA-CHUNK-002"], insufficient_evidence=False)
    a14 = score_answer(gt13, ans14, ["MESA-CHUNK-001", "MESA-CHUNK-002"], id_map)
    assert a14.status == "FAIL" and any("Cited evidence does not intersect" in r for r in a14.reasons)
    results.append({"case": 14, "name": "correct wording but unsupported evidence", "status": "PASS"})

    # --- Test 15: Unicode/Turkish normalization fixtures ---
    t_raw = "  İSTANBUL   Hukuk   Fakültesi  \r\n  Madde  14   "
    t_norm = normalize_text(t_raw)
    assert "İSTANBUL Hukuk Fakültesi\nMadde 14" == t_norm
    t_case = turkish_casefold("İSTANBUL IŞIK")
    assert t_case == "istanbul ışık"
    assert normalize_law_id("4857 sayılı Kanun") == "4857"
    assert normalize_law_id("Kanun No: 4857") == "4857"
    assert normalize_article_id("Madde 14") == "madde-14"
    assert normalize_article_id("14. madde") == "madde-14"
    results.append({"case": 15, "name": "Unicode/Turkish normalization fixtures", "status": "PASS"})

    # --- Test 16: Intentionally wrong qrel expected to fail ---
    gt16 = GroundTruthItem(query_id="TEST-16", query_class="SINGLE_DIRECT", question="Q", expected_source_chunk_ids=["SRC-WRONG-999"])
    ret16 = [{"chunk_id": "MESA-CHUNK-001"}]
    s16 = score_retrieval(gt16, ret16, id_map)
    assert s16.status == "MISS" and s16.recall_at_5 == 0.0
    results.append({"case": 16, "name": "intentionally wrong qrel expected to fail", "status": "PASS"})

    # --- Test 17: Intentionally wrong answer expected to fail ---
    ans17 = AnswerResponse(answer="Tamamen Yanlış ve Uydurma Bilgi", evidence_chunk_ids=["MESA-CHUNK-001"], insufficient_evidence=False)
    a17 = score_answer(gt13, ans17, ["MESA-CHUNK-001"], id_map)
    assert a17.status == "FAIL" and a17.grounded_pass is False
    results.append({"case": 17, "name": "intentionally wrong answer expected to fail", "status": "PASS"})

    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_cases": len(results),
        "passed_cases": sum(1 for r in results if r["status"] == "PASS"),
        "failed_cases": sum(1 for r in results if r["status"] != "PASS"),
        "all_passed": all(r["status"] == "PASS" for r in results),
        "cases": results
    }

if __name__ == "__main__":
    report = run_harness_self_tests()
    print(f"Harness Self-Test Results: {report['passed_cases']}/{report['total_cases']} passed (all_passed={report['all_passed']})")
