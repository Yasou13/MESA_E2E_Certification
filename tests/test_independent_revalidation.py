"""Third-sweep mutation checks that reach the intended production boundary."""
import json

import pytest

from tests.independent_support import transaction, placeholder_sources, NOW
from tests.test_independent_boundaries import reseal
from harness.transaction import TransactionError
from harness.evidence import build_evidence_index, EvidenceIndexError
from harness.finalizer import finalize_release, ReleaseFinalizationError


def test_gate_evaluation_revalidates_oracle_after_scoring(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    tx.execute_scoring()
    p = tx.run_dir / "oracle-leakage-audit.json"
    pl = json.loads(p.read_text()); pl["status"] = "FAIL"
    pl["finding_count"] = 1; pl["findings"] = [{"kind": "oracle leak"}]
    p.write_text(json.dumps(pl)); reseal(p)
    with pytest.raises(TransactionError, match="oracle|audit"):
        tx.execute_gate_evaluation()


def test_score_report_mutation_detected_by_gate_phase(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    tx.execute_scoring()
    p = tx.run_dir / "scoring-report.json"
    pl = json.loads(p.read_text()); pl["items"][0]["status"] = "PASS"
    p.write_text(json.dumps(pl))
    with pytest.raises(TransactionError, match="score|scoring|hash|seal"):
        tx.execute_gate_evaluation()


def test_evidence_path_aliases_are_duplicates(tmp_path):
    (tmp_path / "artifact.json").write_text('{"run_id":"R"}')
    base = {"producer": "test", "phase": "test", "timestamp_utc": NOW,
            "source_run_id": "R", "immutable": True, "sealed": True}
    with pytest.raises(EvidenceIndexError, match="canonical|duplicate"):
        build_evidence_index(tmp_path, tmp_path / "evidence-index.json",
            [{**base, "path": "artifact.json"}, {**base, "path": "./artifact.json"}], run_id="R")


def test_nonpass_archive_does_not_mask_evidence_mutation(tmp_path):
    sources = placeholder_sources(tmp_path)
    p = sources["gate-results.json"]
    pl = json.loads(p.read_text()); pl["final_verdict"] = "PROFILE_B_BLOCKED_PRECONDITION"
    p.write_text(json.dumps(pl))
    sources["answer-summary.json"].write_text(json.dumps({"schema_version":"1.0", "run_id":"RUN-independent", "changed": True}))
    with pytest.raises(ReleaseFinalizationError, match="hash mismatch"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
