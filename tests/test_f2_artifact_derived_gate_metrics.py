"""Regression tests for F2: gate metrics derived from authoritative score artifacts."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.gates import GateStatus, load_gate_config
from harness.models import ExecutionStatus, GateResult, VerdictStatus
from harness.transaction import CertificationTransaction, TransactionError
from harness.artifacts import RunArtifactStore

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
RUN_ID = "RUN-20260925T160000Z-f2test"


def _make_freeze(tmp_path: Path, run_id: str):
    freeze_dir = tmp_path / "freeze"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    materials = {}
    for cat in sorted(MANDATORY_MATERIAL_CATEGORIES):
        p = freeze_dir / f"{cat}.txt"
        p.write_text(cat, encoding="utf-8")
        materials[cat] = [p]

    repository_shas = {
        "MESA": "a" * 40,
        "MESA_Data": "b" * 40,
        "MESA_E2E_Certification": "c" * 40,
    }
    freeze_path, checksum_path = create_contract_freeze(
        output_dir=freeze_dir,
        run_id=run_id,
        repository_root=freeze_dir,
        repository_shas=repository_shas,
        material_paths=materials,
        runtime_identities={"python": "3.13.12"},
        created_at=datetime.now(timezone.utc),
    )
    return freeze_path, checksum_path, freeze_dir, repository_shas


def _setup_tx_with_raw(tmp_path: Path, run_id: str = RUN_ID) -> tuple[CertificationTransaction, Path]:
    run_dir = tmp_path / run_id
    freeze_path, checksum_path, freeze_dir, repo_shas = _make_freeze(tmp_path, run_id)
    tx = CertificationTransaction(run_id, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=freeze_dir, current_repository_shas=repo_shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, run_id)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "chunk_1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    return tx, run_dir


# 1. caller attempts fake passing metrics -> ignored/rejected
def test_1_caller_fake_passing_metrics_rejected(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    # Scorer generates a failing score (e.g. recall = 0.10)
    tx.execute_scoring(scoring_fn=lambda r: {"query_id": "Q-1", "status": "FAIL", "lane": "retrieval", "recall_at_5": 0.10, "mrr": 0.10})
    
    # Caller supplies fake passing metrics claiming recall_at_5 is 0.99
    fake_metrics = {"B10": {"answerable_recall_at_5": 0.99, "answerable_mrr": 0.99, "rel_complete_evidence_at_5": 0.99, "single_hop_recall_at_5": 0.99, "tenant_leakage": 0}}
    results = tx.execute_gate_evaluation(gate_metrics=fake_metrics, gate_evidence={})
    b10_res = next(g for g in results if g.gate_id == "B10")
    # Gate B10 must NOT pass on fake metrics; it must reflect the real failing score
    assert b10_res.status != GateStatus.PASS


# 2. official score artifact contains failing Recall@5 -> B10 FAIL
def test_2_official_score_artifact_failing_recall_causes_b10_fail(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    # Recall 0.50 is below mandatory threshold 0.80
    tx.execute_scoring(scoring_fn=lambda r: {"query_id": "Q-1", "status": "FAIL", "lane": "retrieval", "recall_at_5": 0.50, "mrr": 0.50})
    results = tx.execute_gate_evaluation()
    b10_res = next(g for g in results if g.gate_id == "B10")
    assert b10_res.status == GateStatus.FAIL
    assert "threshold_not_met" in b10_res.reason or "missing" in b10_res.reason or b10_res.status == GateStatus.FAIL


# 3. serialized metric artifact tampered -> detected
def test_3_serialized_metric_artifact_tampered_detected(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    tx.execute_scoring()
    # Tamper with scoring-summary.json
    summary_path = run_dir / "scoring-summary.json"
    summary_path.write_text('{"tampered": true, "raw_manifest_hash": "bad"}\n')
    with pytest.raises(TransactionError, match="tamper|hash|seal|integrity|invalid"):
        tx.execute_gate_evaluation()


# 4. score artifact from different raw manifest -> rejected
def test_4_score_artifact_different_raw_manifest_rejected(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    tx.execute_scoring()
    # Modify summary raw manifest hash
    summary_path = run_dir / "scoring-summary.json"
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    data["raw_manifest_hash"] = "0" * 64
    summary_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    content = summary_path.read_bytes()
    h = hashlib.sha256(content).hexdigest()
    (run_dir / "scoring-summary.json.SHA256").write_text(f"{h}  scoring-summary.json\n", encoding="utf-8")
    with pytest.raises(TransactionError, match="manifest|mismatch|stale|tamper|mutated"):
        tx.execute_gate_evaluation()


# 5. missing score artifact -> gate UNVERIFIED/FAIL-CLOSED
def test_5_missing_score_artifact_fail_closed(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    tx.execute_scoring()
    # Delete score summary
    (run_dir / "scoring-summary.json").unlink()
    if (run_dir / "scoring-summary.json.SHA256").is_file():
        (run_dir / "scoring-summary.json.SHA256").unlink()
    with pytest.raises(TransactionError, match="missing score artifact|scoring"):
        tx.execute_gate_evaluation()


# 6. fake evidence path -> gate cannot PASS
def test_6_fake_evidence_path_cannot_pass(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    tx.execute_scoring()
    fake_evidence = {"B10": ["nonexistent_file_path.json"]}
    results = tx.execute_gate_evaluation(gate_evidence=fake_evidence)
    b10_res = next(g for g in results if g.gate_id == "B10")
    assert b10_res.status != GateStatus.PASS


# 7. empty score artifact -> hard gate cannot PASS
def test_7_empty_score_artifact_hard_gate_cannot_pass(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, freeze_dir, repo_shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=freeze_dir, current_repository_shas=repo_shas)
    tx.execute_raw_execution(lambda d: None)
    # Zero raw records fails scoring or gate evaluation
    with pytest.raises(TransactionError):
        tx.execute_raw_sealing()
        tx.execute_oracle_audit()
        tx.execute_scoring()
        tx.execute_gate_evaluation()


# 8. all official score artifacts valid -> observations computed and gates evaluated
def test_8_all_official_score_artifacts_valid_evaluates(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    tx.execute_scoring(scoring_fn=lambda r: {
        "query_id": "Q-1",
        "status": "PASS",
        "lane": "retrieval",
        "recall_at_5": 1.0,
        "mrr": 1.0,
        "answerable_recall_at_5": 1.0,
        "answerable_mrr": 1.0,
        "rel_complete_evidence_at_5": 1.0,
        "single_hop_recall_at_5": 1.0,
        "tenant_leakage": 0,
    })
    results = tx.execute_gate_evaluation()
    assert len(results) >= 15
    b10_res = next(g for g in results if g.gate_id == "B10")
    assert b10_res.status == GateStatus.PASS


# 9. threshold change after freeze -> invalidation
def test_9_threshold_change_after_freeze_invalidation(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    tx.execute_scoring()
    # Tamper with the gate config path (e.g. lowering threshold)
    tampered_config = run_dir / "tampered-gates.json"
    tampered_config.write_text('{"schema_version": "1.0", "mandatory_gate_ids": ["B10"], "gates": {}, "methodology_note": ""}\n')
    tx.gate_config_path = tampered_config
    with pytest.raises(Exception):
        tx.execute_gate_evaluation()


# 10. B0–B14 completeness still enforced
def test_10_b0_b14_completeness_enforced(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx_with_raw(tmp_path)
    tx.execute_scoring()
    results = tx.execute_gate_evaluation()
    evaluated_ids = {g.gate_id for g in results}
    expected_mandatory = {f"B{i}" for i in range(15)}
    assert expected_mandatory.issubset(evaluated_ids)
