from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from harness.freeze import (
    MANDATORY_MATERIAL_CATEGORIES,
    create_contract_freeze,
)
from harness.transaction import (
    CertificationTransaction,
    TransactionError,
    TransactionPhase,
)
from harness.models import VerdictStatus


RUN_ID = "RUN-20260925T140000Z-c8test"


def _valid_freeze(tmp_path: Path, run_id: str) -> tuple[Path, Path, dict[str, str]]:
    materials: dict[str, list[Path]] = {}
    for cat in sorted(MANDATORY_MATERIAL_CATEGORIES):
        p = tmp_path / f"{cat}.txt"
        p.write_text(cat, encoding="utf-8")
        materials[cat] = [p]

    repository_shas = {
        "MESA": "a" * 40,
        "MESA_Data": "b" * 40,
        "MESA_E2E_Certification": "c" * 40,
    }
    freeze_path, checksum_path = create_contract_freeze(
        output_dir=tmp_path,
        run_id=run_id,
        repository_root=tmp_path,
        repository_shas=repository_shas,
        material_paths=materials,
        runtime_identities={"python": "3.13.12"},
        created_at=datetime.now(timezone.utc),
    )
    return freeze_path, checksum_path, repository_shas


def _pass_all_gates_metrics() -> dict[str, dict]:
    return {
        "B0": {
            "ci_actions_passed": True,
            "clean_baseline_verified": True,
            "dedicated_branch_verified": True,
            "dependencies_reproducible": True,
        },
        "B1": {
            "disk_min_gb": 100,
            "isolated_storage_verified": True,
            "ram_min_gb": 64,
        },
        "B2": {
            "gpt_oss_completion_verified": True,
            "nemotron_dim_verified": True,
            "real_provider_contract_verified": True,
        },
        "B3": {
            "docker_config_parity": True,
            "frozen_provider_parity": True,
        },
        "B4": {
            "eligible_document_count": 60,
            "encoding_canonical_verified": True,
            "raw_integrity_verified": True,
        },
        "B5": {
            "delivery_permission_granted": True,
            "h1_approval_hash_bound": True,
        },
        "B6": {
            "canary_passed": True,
            "no_bridge_substitution": True,
        },
        "B7": {
            "chunk_mapping_proven": True,
            "delivery_terminal_committed": True,
            "undelivered_chunk_count": 0,
        },
        "B8": {
            "idempotent_republish_proven": True,
            "restart_persistence_proven": True,
        },
        "B9": {
            "cross_tenant_scope_leakage": 0,
            "isolation_acl_passed": True,
        },
        "B10": {
            "answerable_mrr": 0.85,
            "answerable_recall_at_5": 0.90,
            "rel_complete_evidence_at_5": 0.80,
            "single_hop_recall_at_5": 0.95,
            "tenant_leakage": 0,
        },
        "B11": {
            "graph_capability_operational": True,
            "graph_causal_ablation_proven": True,
            "graph_provenance_verified": True,
            "graph_rel_contribution_count": 5,
        },
        "B12": {
            "answerable_pass_rate": 0.90,
            "fabricated_evidence_chunk_ids": 0,
            "no_answer_pass_rate": 0.95,
            "unsupported_material_claim_rate": 0,
        },
        "B13": {
            "catastrophic_resource_failure": 0,
            "oom_killed_count": 0,
            "resource_usage_recorded": True,
        },
        "B14": {
            "evidence_integrity_verified": True,
            "post_freeze_mutations": 0,
        },
    }


def test_out_of_order_scoring_before_oracle_audit_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    tx.execute_freeze(
        freeze_path, checksum_path, repository_root=tmp_path, current_repository_shas=shas
    )

    # Attempt to skip to scoring
    with pytest.raises(TransactionError, match="Out-of-order"):
        tx.execute_scoring([])


def test_out_of_order_finalization_before_gates_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()

    with pytest.raises(TransactionError, match="Out-of-order"):
        tx.execute_release_finalization(tmp_path / "release")


def test_failure_at_freeze_phase_aborts_before_execution(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()

    missing_freeze = tmp_path / "nonexistent-freeze.json"
    missing_checksum = tmp_path / "nonexistent-checksum.SHA256"
    with pytest.raises(TransactionError, match="Contract freeze verification failed"):
        tx.execute_freeze(
            missing_freeze,
            missing_checksum,
            repository_root=tmp_path,
            current_repository_shas={},
        )

    assert tx.failed is True
    # Further phase must be blocked
    with pytest.raises(TransactionError, match="Transaction has failed at a previous phase"):
        tx.execute_raw_execution(lambda d: None)


def test_failure_at_oracle_phase_aborts_before_scoring(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    tx.execute_freeze(
        freeze_path, checksum_path, repository_root=tmp_path, current_repository_shas=shas
    )

    def make_raw(d: Path) -> None:
        (d / "query_log.txt").write_text("sample log", encoding="utf-8")

    tx.execute_raw_execution(make_raw)
    tx.execute_raw_sealing()

    # Oracle audit surface has forbidden leaked value
    oracle_surfaces = [{"path": "surface.json", "content": "oracle_secret_answer"}]
    with pytest.raises(TransactionError, match="oracle audit failed"):
        tx.execute_oracle_audit(oracle_surfaces, known_oracle_values={"oracle_secret_answer"})

    assert tx.failed is True
    # Attempting to score after oracle audit failure must be rejected
    with pytest.raises(TransactionError, match="Transaction has failed at a previous phase"):
        tx.execute_scoring([])


def test_failure_at_gate_evaluation_refuses_finalization(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    tx.execute_freeze(
        freeze_path, checksum_path, repository_root=tmp_path, current_repository_shas=shas
    )

    def make_raw(d: Path) -> None:
        (d / "raw.txt").write_text("raw", encoding="utf-8")

    tx.execute_raw_execution(make_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit([])
    tx.execute_scoring([])

    # Metrics fail B10 (e.g. recall below threshold)
    metrics = _pass_all_gates_metrics()
    metrics["B10"]["answerable_recall_at_5"] = 0.50 # Threshold is 0.80!
    tx.execute_gate_evaluation(metrics, {})

    verdict = tx.execute_verdict_derivation()
    assert verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE

    records = [
        {
            "path": "raw.txt",
            "sha256": "b" * 64,
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": datetime.now(timezone.utc),
            "source_run_id": RUN_ID,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        }
    ]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()
    tx.execute_health_verification()

    # Finalization must be refused!
    with pytest.raises(TransactionError, match="Cannot finalize release with non-PASS verdict"):
        tx.execute_release_finalization(tmp_path / "release")


def test_full_successful_transaction_produces_valid_release(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    release_dir = tmp_path / "release"
    tx = CertificationTransaction(RUN_ID, run_dir)

    tx.execute_bootstrap()
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    tx.execute_freeze(
        freeze_path, checksum_path, repository_root=tmp_path, current_repository_shas=shas
    )

    def make_raw(d: Path) -> None:
        (d / "query_trace.txt").write_text("ok", encoding="utf-8")
        (d / "retrieval-test-report.json").write_text(
            json.dumps({"schema_version": "1.0", "run_id": RUN_ID, "summary": {"overall_recall_at_5": 0.9}}),
            encoding="utf-8"
        )

    tx.execute_raw_execution(make_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit([])
    tx.execute_scoring([])

    metrics = _pass_all_gates_metrics()
    tx.execute_gate_evaluation(metrics, {})
    verdict = tx.execute_verdict_derivation()
    assert verdict.status == VerdictStatus.PROFILE_B_PASS_NATIVE

    raw_path = run_dir / "query_trace.txt"
    raw_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    ret_path = run_dir / "retrieval-test-report.json"
    ret_hash = hashlib.sha256(ret_path.read_bytes()).hexdigest()

    now = datetime.now(timezone.utc)
    records = [
        {
            "path": "query_trace.txt",
            "sha256": raw_hash,
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": now,
            "source_run_id": RUN_ID,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        },
        {
            "path": "retrieval-test-report.json",
            "sha256": ret_hash,
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": now,
            "source_run_id": RUN_ID,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        }
    ]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()
    tx.execute_health_verification()

    release_meta = tx.execute_release_finalization(release_dir)
    assert release_meta["run_id"] == RUN_ID
    promoted_dir = Path(release_meta["release_dir"])
    assert promoted_dir.is_dir()
    assert (promoted_dir / "gate-results.json").is_file()
    assert (promoted_dir / "SHA256SUMS.txt").is_file()
    assert TransactionPhase.COMPLETED in tx.completed_phases
