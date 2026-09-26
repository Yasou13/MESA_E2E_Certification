"""Independent production-path attacks; no imported happy-path fixtures."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from harness.artifacts import RunArtifactStore
from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.transaction import CertificationTransaction, TransactionError
from harness.models import AnswerClaim, AnswerResponse, GroundTruthItem
from harness.answer_scorer import score_answer
from harness.identity import IdentityMap
from harness.evidence import build_evidence_index, validate_run_id_consistency
from harness.finalizer import REQUIRED_RELEASE_FILES, finalize_release, ReleaseFinalizationError

from tests.independent_support import transaction, score_claims, placeholder_sources

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]




def test_oracle_surface_collision_cannot_hide_raw(tmp_path):
    tx = transaction(tmp_path, request={"required_facts": ["SECRET-FACT"]})
    with pytest.raises(TransactionError, match="oracle audit failed"):
        tx.execute_oracle_audit({"raw/retrieval/Q-audit.json": {"query": "clean"}})


def test_empty_retrieval_response_is_not_scored_as_hit(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    result = tx.execute_scoring()
    assert result["status"] != "PASS"
    assert not result["items"][0].get("recall_at_5", 0)


def test_custom_scorer_cannot_force_pass(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    result = tx.execute_scoring(scoring_fn=lambda _: {"query_id": "Q-audit",
        "lane": "retrieval", "status": "PASS", "recall_at_5": 1, "mrr": 1})
    assert result["status"] != "PASS"


def test_all_gate_metrics_are_authoritative(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    tx.execute_scoring()
    cfg = json.loads(tx.gate_config_path.read_text())
    injected = {gid: {m: r["value"] for m, r in d["requirements"].items()}
        for gid, d in cfg["gates"].items()}
    gates = tx.execute_gate_evaluation(injected,
        {gid: ["contract-freeze.json"] for gid in injected})
    assert all(g.status.value != "PASS" for g in gates)


def test_threshold_change_rejected_before_gate_evaluation(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    tx.execute_scoring()
    cfg = json.loads(tx.gate_config_path.read_text())
    cfg["gates"]["B10"]["requirements"]["answerable_mrr"]["value"] = 0
    tx.gate_config_path.write_text(json.dumps(cfg))
    with pytest.raises(TransactionError, match="freeze|threshold|config"):
        tx.execute_gate_evaluation()












def test_placeholder_pass_bundle_is_rejected(tmp_path):
    sources = placeholder_sources(tmp_path)
    with pytest.raises(ReleaseFinalizationError):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")


def test_real_index_mutated_artifact_rejected_by_finalizer(tmp_path):
    sources = placeholder_sources(tmp_path)
    p = sources["answer-summary.json"]
    payload = json.loads(p.read_text())
    payload["mutated"] = True
    p.write_text(json.dumps(payload))
    with pytest.raises(ReleaseFinalizationError):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")


def test_health_requires_measurements(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    tx.execute_scoring()
    tx.execute_gate_evaluation()
    tx.execute_verdict_derivation()
    tx.execute_evidence_index([{"path": "raw/retrieval/Q-audit.json", "producer": "independent",
        "phase": "test", "timestamp_utc": NOW, "source_run_id": tx.run_id,
        "immutable": True, "sealed": True}])
    tx.execute_run_id_consistency()
    with pytest.raises(TransactionError, match="health|measurement|missing"):
        tx.execute_health_verification()
