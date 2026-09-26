"""Independent evidence-rank and production freeze rejection checks."""
import hashlib
import json

import pytest

from tests.independent_support import transaction
from harness.transaction import CertificationTransaction, TransactionError
from harness.identity import IdentityMap
from harness.models import GroundTruthItem
from harness.retrieval_scorer import score_retrieval


@pytest.mark.parametrize("case", ["deep_provenance", "same_document_wrong_chunk", "rank_six",
                                  "duplicate_ids", "malformed_provenance", "rel_partial", "rel_complete", "no_answer"])
def test_evidence_rank(case):
    ids = IdentityMap()
    for name in ["ENTITY", "GOLD", "SECOND", "OTHER"]:
        ids.add_mapping("M-"+name, "S-"+name)
    gt = GroundTruthItem(query_id="Q", query_class="SINGLE_DIRECT", question="test",
                         expected_source_chunk_ids=["S-GOLD"])
    results = [{"chunk_id":"M-OTHER"}]
    if case == "deep_provenance":
        results = [{"id":"M-ENTITY", "provenance":
                    [{"chunk_id":"M-OTHER"} for _ in range(99)]+[{"chunk_id":"M-GOLD"}]}]
    elif case == "same_document_wrong_chunk":
        results = [{"chunk_id":"M-OTHER", "document_id":"same-law", "article":"same-article"}]
    elif case == "rank_six":
        results = [{"chunk_id":"M-OTHER"} for _ in range(5)]+[{"chunk_id":"M-GOLD"}]
    elif case == "duplicate_ids":
        results = [{"chunk_id":"M-GOLD"}, {"chunk_id":"M-GOLD"}]
    elif case == "malformed_provenance":
        results = [{"chunk_id":"M-GOLD", "provenance":["not-an-object"]}]
    elif case.startswith("rel_"):
        gt.query_class = "RELATIONAL"
        from harness.models import EvidenceGroup
        gt.evidence_groups = [EvidenceGroup(group_id="first", acceptable_source_chunk_ids=["S-GOLD"]),
                              EvidenceGroup(group_id="second", acceptable_source_chunk_ids=["S-SECOND"])]
        results = [{"chunk_id":"M-GOLD"}]
        if case == "rel_complete": results.append({"chunk_id":"M-SECOND"})
    elif case == "no_answer":
        gt.query_class = "NO_ANSWER"; gt.is_answerable = False
    score = score_retrieval(gt, results, ids)
    if case in {"deep_provenance", "same_document_wrong_chunk", "rank_six"}:
        assert score.rank is None and score.recall_at_5 == 0 and score.mrr == 0
    elif case == "duplicate_ids":
        assert score.rank == 1 and score.matching_chunk_ids == ["S-GOLD"]
    elif case == "malformed_provenance":
        assert score.status == "MAPPING_INTEGRITY_ERROR"
    elif case == "rel_partial":
        assert score.complete_evidence_at_5 == 0 and score.group_coverage_at_5 == .5
    elif case == "rel_complete":
        assert score.complete_evidence_at_5 == 1 and score.group_coverage_at_5 == 1
    else:
        assert score.status == "NO_ANSWER_EVALUATED_IN_ANSWER_STAGE"


@pytest.mark.parametrize("case", ["empty_shas", "missing_sha", "empty_materials", "missing_category",
                                  "duplicate_material", "wrong_sidecar", "changed_bytes", "schema"])
def test_invalid_freeze_cannot_enter_transaction(tmp_path, case):
    original = transaction(tmp_path)
    freeze = original.freeze_path
    sidecar = original.checksum_path
    payload = json.loads(freeze.read_text())
    if case == "empty_shas": payload["repository_shas"] = {}
    elif case == "missing_sha": payload["repository_shas"].pop("MESA")
    elif case == "empty_materials": payload["materials"] = []
    elif case == "missing_category": payload["materials"] = [m for m in payload["materials"] if m["category"] != "prompts"]
    elif case == "duplicate_material": payload["materials"].append({**payload["materials"][0], "sha256":"0"*64})
    elif case == "schema": payload["schema_version"] = "unknown"
    freeze.write_text(json.dumps(payload))
    digest = hashlib.sha256(freeze.read_bytes()).hexdigest()
    sidecar.write_text(("0"*64 if case == "wrong_sidecar" else digest)+"  contract-freeze.json\n")
    if case == "changed_bytes": freeze.write_text(freeze.read_text()+" ")
    tx = CertificationTransaction(original.run_id, tmp_path / "second" / original.run_id)
    tx.execute_bootstrap()
    with pytest.raises(TransactionError, match="Contract freeze verification failed"):
        tx.execute_freeze(freeze, sidecar, repository_root=original.repository_root,
                          current_repository_shas=original.current_repository_shas)
    with pytest.raises(TransactionError, match="previous phase"):
        tx.execute_raw_execution(lambda _: pytest.fail("raw execution must not run"))
