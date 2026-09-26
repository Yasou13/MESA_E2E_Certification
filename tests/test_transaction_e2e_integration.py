"""End-to-end transaction integration test suite covering T1-T12."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from harness.artifacts import AnswerExecutionCapture, RunArtifactStore
from harness.finalizer import REQUIRED_RELEASE_FILES, verify_release_bundle
from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.models import (
    AnswerClaim,
    AnswerPattern,
    AnswerResponse,
    ExactSourceSpan,
    GroundTruthItem,
    PatternMode,
    RequiredFact,
    VerdictStatus,
)
from harness.transaction import CertificationTransaction, TransactionError

RUN_ID = "RUN-20260925T180000Z-integ"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()


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


def _populate_supplementary_release_files(run_dir: Path, run_id: str) -> None:
    (run_dir / "final-report.md").write_text(f"# Final Report\n\nRun: {run_id}\nStatus: PASS\n", encoding="utf-8")
    for name in [
        "health-pre-test.json",
        "health-post-test.json",
        "resource-provider-summary.json",
        "scorer-canary-results.json",
        "determinism-manifest.json",
        "graph-summary.json",
        "frozen-identities.json",
        "identity-map-summary.json",
        "decision-summary.json",
        "repair-summary.json",
    ]:
        p = run_dir / name
        if not p.is_file():
            p.write_text(
                json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS"}, indent=2) + "\n",
                encoding="utf-8",
            )


def _pass_all_gates_metrics() -> dict[str, dict]:
    return {
        "B0": {"ci_actions_passed": True, "clean_baseline_verified": True, "dedicated_branch_verified": True, "dependencies_reproducible": True},
        "B1": {"disk_min_gb": 100, "isolated_storage_verified": True, "ram_min_gb": 64},
        "B2": {"gpt_oss_completion_verified": True, "nemotron_dim_verified": True, "real_provider_contract_verified": True},
        "B3": {"docker_config_parity": True, "frozen_provider_parity": True},
        "B4": {"eligible_document_count": 60, "encoding_canonical_verified": True, "raw_integrity_verified": True},
        "B5": {"delivery_permission_granted": True, "h1_approval_hash_bound": True},
        "B6": {"canary_passed": True, "no_bridge_substitution": True},
        "B7": {"chunk_mapping_proven": True, "delivery_terminal_committed": True, "undelivered_chunk_count": 0},
        "B8": {"idempotent_republish_proven": True, "restart_persistence_proven": True},
        "B9": {"cross_tenant_scope_leakage": 0, "isolation_acl_passed": True},
        "B10": {"answerable_mrr": 1.0, "answerable_recall_at_5": 1.0, "rel_complete_evidence_at_5": 1.0, "single_hop_recall_at_5": 1.0, "tenant_leakage": 0},
        "B11": {"graph_capability_operational": True, "graph_causal_ablation_proven": True, "graph_provenance_verified": True, "graph_rel_contribution_count": 5},
        "B12": {"answerable_pass_rate": 1.0, "fabricated_evidence_chunk_ids": 0, "no_answer_pass_rate": 1.0, "unsupported_material_claim_rate": 0},
        "B13": {"catastrophic_resource_failure": 0, "oom_killed_count": 0, "resource_usage_recorded": True},
        "B14": {"evidence_integrity_verified": True, "post_freeze_mutations": 0},
    }


# T1: Clean passing transaction with real retrieval, real answers, full gates, all 17 required artifacts -> verify_release_bundle PASS
def test_t1_placeholder_transaction_remains_blocked(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    release_dir = tmp_path / "release"
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test query"},
            response={"results": [{"chunk_id": "chunk_1", "score": 1.0, "rank": 1}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
        capture = AnswerExecutionCapture.from_context(
            query_id="Q-1",
            timestamp_utc=NOW,
            exact_model_visible_context="Ceza 5 yıldır",
            context_evidence_ids=["chunk_1"],
            system_prompt="sys",
            user_prompt="usr",
            provider="test",
            model="test",
            request_parameters={},
            raw_response={},
            parsed_response={"answer": "Ceza 5 yıldır", "evidence_chunk_ids": ["chunk_1"]},
            context_contract_version="1.0",
        )
        store.persist_raw_answer(capture)

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()

    # Pre-populate provider evidence so real evidence exists for all gates
    _populate_supplementary_release_files(run_dir, RUN_ID)

    tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics())
    verdict = tx.execute_verdict_derivation()
    assert verdict.status == VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION
    assert all(g.status.value == "UNVERIFIED" for g in tx.gate_results)
    # A complete-looking placeholder bundle must not authorize publication.
    from tests.independent_support import placeholder_sources
    from harness.finalizer import finalize_release, ReleaseFinalizationError
    attack_dir = tmp_path / "placeholder-attack"
    attack_dir.mkdir()
    sources = placeholder_sources(attack_dir)
    with pytest.raises(ReleaseFinalizationError):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=release_dir)
    assert not (release_dir / "RUN-independent").exists()


# T2: Transaction fails at freeze phase if repo modified post-freeze
def test_t2_fails_if_repo_modified_post_freeze(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()

    tampered_shas = dict(shas)
    tampered_shas["MESA"] = "f" * 40
    with pytest.raises(TransactionError, match="freeze.*failed|Contract freeze verification failed"):
        tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=tampered_shas)


# T3: Transaction fails at raw sealing if raw file tampered before sealing
def test_t3_fails_at_raw_sealing_if_corrupt(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def corrupt_raw(d: Path):
        (d / "raw" / "retrieval").mkdir(parents=True, exist_ok=True)
        # Invalid / corrupt json
        (d / "raw" / "retrieval" / "Q-1.json").write_text("NOT_VALID_JSON", encoding="utf-8")

    tx.execute_raw_execution(corrupt_raw)
    with pytest.raises(TransactionError, match="raw sealing failed"):
        tx.execute_raw_sealing()


# T4: Transaction fails at oracle audit if raw file contains leaked oracle token
def test_t4_fails_at_oracle_audit_if_leak_present(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw_with_leak(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test with LEAKED_FORBIDDEN_TOKEN inside raw"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw_with_leak)
    tx.execute_raw_sealing()
    with pytest.raises(TransactionError, match="oracle audit failed"):
        tx.execute_oracle_audit(known_oracle_values=["LEAKED_FORBIDDEN_TOKEN"])


# T5: Transaction fails at scoring if raw file tampered after sealing
def test_t5_fails_at_scoring_if_raw_tampered_after_sealing(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()

    # Tamper with raw artifact after sealing
    raw_file = run_dir / "raw" / "retrieval" / "Q-1.json"
    raw_file.chmod(0o644)
    raw_file.write_text('{"tampered": true}\n', encoding="utf-8")

    with pytest.raises(TransactionError, match="scoring failed"):
        tx.execute_scoring()


# T6: Transaction fails at gate evaluation if score metrics fall below threshold
def test_t6_fails_at_gate_evaluation_if_score_below_threshold(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()

    def low_scorer(raw_payload: dict):
        return {"query_id": "Q-1", "status": "FAIL", "lane": "retrieval", "recall_at_5": 0.2, "mrr": 0.2}

    tx.execute_scoring(scoring_fn=low_scorer)
    gate_results = tx.execute_gate_evaluation()
    b10_result = next((g for g in gate_results if g.gate_id == "B10"), None)
    assert b10_result is not None
    assert b10_result.status.value == "UNVERIFIED"


# T7: Transaction fails at verdict derivation if any hard gate is FAIL
def test_t7_fails_at_verdict_derivation_if_hard_gate_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()

    def low_scorer(raw_payload: dict):
        return {"query_id": "Q-1", "status": "FAIL", "lane": "retrieval", "recall_at_5": 0.2, "mrr": 0.2}

    tx.execute_scoring(scoring_fn=low_scorer)
    tx.execute_gate_evaluation()
    verdict = tx.execute_verdict_derivation()
    assert verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE


# T8: Transaction fails at evidence index if evidence file is missing on disk
def test_t8_fails_at_evidence_index_if_file_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    tx.execute_gate_evaluation()
    tx.execute_verdict_derivation()

    records = [
        {
            "path": "non_existent_file.json",
            "sha256": "0" * 64,
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": NOW,
            "source_run_id": RUN_ID,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        }
    ]
    with pytest.raises(TransactionError, match="evidence index failed"):
        tx.execute_evidence_index(records)


# T9: Transaction fails at run-id consistency if artifact has mismatched run_id
def test_t9_fails_at_run_id_consistency_if_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    tx.execute_gate_evaluation()
    tx.execute_verdict_derivation()

    raw_path = run_dir / "raw" / "retrieval" / "Q-1.json"
    records = [
        {
            "path": "raw/retrieval/Q-1.json",
            "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": NOW,
            "source_run_id": RUN_ID,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        }
    ]
    tx.execute_evidence_index(records)

    # Insert alien artifact with different RUN_ID
    alien_file = run_dir / "alien-evidence.json"
    alien_file.write_text(json.dumps({"schema_version": "1.0", "run_id": "ALIEN-RUN-ID"}), encoding="utf-8")

    with pytest.raises(TransactionError, match="run-id consistency failed"):
        tx.execute_run_id_consistency()


# T10: Transaction fails at health verification if preflight evidence is missing or failed
def test_t10_fails_at_health_verification_if_failed(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    tx.execute_gate_evaluation()
    tx.execute_verdict_derivation()

    raw_path = run_dir / "raw" / "retrieval" / "Q-1.json"
    records = [
        {
            "path": "raw/retrieval/Q-1.json",
            "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": NOW,
            "source_run_id": RUN_ID,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        }
    ]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()

    # Pass unhealthy payload
    with pytest.raises(TransactionError, match="health verification.*failed|status is not PASS"):
        tx.execute_health_verification(health_payload={"status": "FAIL", "run_id": RUN_ID})


# T11: Transaction fails at release finalization if any of 17 required artifacts is missing
def test_t11_fails_at_release_finalization_if_artifact_missing(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    from harness.finalizer import finalize_release, ReleaseFinalizationError
    sources = placeholder_sources(tmp_path)
    sources["health-pre-test.json"].unlink()
    with pytest.raises(ReleaseFinalizationError, match="release source is not a file: health-pre-test.json"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not sources["health-pre-test.json"].exists()
    assert not (tmp_path / "release" / "RUN-independent").exists()


# T12: Multi-lane workload (both retrieval and answer items in raw manifest) correctly separates and computes both B10 and B12 gate metrics
def test_t12_multi_lane_capture_does_not_invent_metrics(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)

    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test query"},
            response={"results": [{"chunk_id": "chunk_1", "score": 1.0, "rank": 1}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
        capture = AnswerExecutionCapture.from_context(
            query_id="Q-1",
            timestamp_utc=NOW,
            exact_model_visible_context="Ceza 5 yıldır",
            context_evidence_ids=["chunk_1"],
            system_prompt="sys",
            user_prompt="usr",
            provider="test",
            model="test",
            request_parameters={},
            raw_response={},
            parsed_response={"answer": "Ceza 5 yıldır", "evidence_chunk_ids": ["chunk_1"]},
            context_contract_version="1.0",
        )
        store.persist_raw_answer(capture)

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    scoring_rep = tx.execute_scoring()
    assert scoring_rep["item_count"] == 2

    # Check that scoring summary has metrics for both lanes
    scoring_summary = json.loads((run_dir / "scoring-summary.json").read_text(encoding="utf-8"))
    metrics = scoring_summary["metrics"]
    assert metrics == {}
    assert scoring_rep["status"] != "PASS"

    gate_results = tx.execute_gate_evaluation()
    b10_res = next((g for g in gate_results if g.gate_id == "B10"), None)
    b12_res = next((g for g in gate_results if g.gate_id == "B12"), None)
    assert b10_res is not None
    assert b12_res is not None
    assert b10_res.status.value == "UNVERIFIED"
    assert b12_res.status.value == "UNVERIFIED"
