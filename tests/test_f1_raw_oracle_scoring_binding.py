"""Regression tests for F1: binding oracle audit and scoring to sealed raw artifacts."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.identity import IdentityMap
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
from harness.artifacts import RunArtifactStore, ArtifactOrderError, ImmutableArtifactError

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
RUN_ID = "RUN-20260925T150000Z-f1test"


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
        "B10": {"answerable_mrr": 0.85, "answerable_recall_at_5": 0.90, "rel_complete_evidence_at_5": 0.80, "single_hop_recall_at_5": 0.95, "tenant_leakage": 0},
        "B11": {"graph_capability_operational": True, "graph_causal_ablation_proven": True, "graph_provenance_verified": True, "graph_rel_contribution_count": 5},
        "B12": {"answerable_pass_rate": 0.90, "fabricated_evidence_chunk_ids": 0, "no_answer_pass_rate": 0.95, "unsupported_material_claim_rate": 0},
        "B13": {"catastrophic_resource_failure": 0, "oom_killed_count": 0, "resource_usage_recorded": True},
        "B14": {"evidence_integrity_verified": True, "post_freeze_mutations": 0},
    }


def _setup_tx(tmp_path: Path, run_id: str = RUN_ID) -> tuple[CertificationTransaction, Path]:
    run_dir = tmp_path / run_id
    freeze_path, checksum_path, freeze_dir, repo_shas = _make_freeze(tmp_path, run_id)
    tx = CertificationTransaction(run_id, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=freeze_dir, current_repository_shas=repo_shas)
    return tx, run_dir


# 1. raw request contains forbidden oracle key -> detected
def test_1_raw_request_forbidden_oracle_key_detected(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test", "expected_answer": "forbidden_key_leak"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    with pytest.raises(TransactionError, match="oracle audit failed"):
        tx.execute_oracle_audit(oracle_surfaces=[])


# 2. raw request contains known gold ID in arbitrary value -> detected
def test_2_raw_request_known_gold_id_in_arbitrary_value_detected(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "normal query", "metadata": {"debug_source": "SRC-GOLD-777"}},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    with pytest.raises(TransactionError, match="oracle audit failed"):
        tx.execute_oracle_audit(oracle_surfaces=[], known_oracle_values={"SRC-GOLD-777"})


# 3. caller passes empty audit surface while raw contains oracle -> detected
def test_3_caller_empty_surface_with_raw_oracle_detected(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "normal", "qrels": ["doc_1"]},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    with pytest.raises(TransactionError, match="oracle audit failed"):
        tx.execute_oracle_audit(oracle_surfaces=[])


# 4. modify raw after audit -> scoring blocked
def test_4_modify_raw_after_audit_blocks_scoring(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "normal"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit(oracle_surfaces=[])

    # Modify raw file after audit
    raw_file = tx.store.raw_retrieval_dir / "Q-1.json"
    raw_file.write_text('{"tampered": true}\n')

    with pytest.raises(TransactionError, match="scoring failed|manifest|tamper|mismatch"):
        tx.execute_scoring(answer_records=[])


# 5. add raw after audit -> scoring blocked
def test_5_add_raw_after_audit_blocks_scoring(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "normal"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit(oracle_surfaces=[])

    # Add raw file after audit
    tx.store.persist_raw_retrieval(
        query_id="Q-2",
        request={"query": "new query"},
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=10.0,
        runtime_lock_sha256="0" * 64,
    )

    with pytest.raises(TransactionError, match="scoring failed|manifest|stale|mismatch"):
        tx.execute_scoring(answer_records=[])


# 6. remove raw after audit -> scoring blocked
def test_6_remove_raw_after_audit_blocks_scoring(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "normal"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit(oracle_surfaces=[])

    # Remove raw file after audit
    raw_file = tx.store.raw_retrieval_dir / "Q-1.json"
    sidecar = raw_file.with_suffix(".json.SHA256")
    raw_file.unlink()
    sidecar.unlink()

    with pytest.raises(TransactionError, match="scoring failed|manifest|missing|mismatch"):
        tx.execute_scoring(answer_records=[])


# 7. scorer cannot substitute caller-provided record for sealed raw record
def test_7_scorer_cannot_substitute_caller_record(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "actual sealed query"},
            response={"results": [{"chunk_id": "chunk_real"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit(oracle_surfaces=[])

    # Caller tries to pass an alternate unsealed answer record for Q-fake
    fake_caller_record = [{"query_id": "Q-fake", "gt": {}, "answer_obj": {}}]
    report = tx.execute_scoring(answer_records=fake_caller_record)
    # The authoritative scored report items must be derived from sealed raw manifest (Q-1), not Q-fake
    scored_query_ids = [item.get("query_id") for item in report.get("items", [])]
    assert "Q-fake" not in scored_query_ids
    assert "Q-1" in scored_query_ids


# 8. raw manifest hash stored in score artifact
def test_8_raw_manifest_hash_stored_in_score_artifact(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "query"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    manifest_hash = tx.execute_raw_sealing()
    tx.execute_oracle_audit(oracle_surfaces=[])
    report = tx.execute_scoring(answer_records=[])
    assert report.get("raw_manifest_hash") == manifest_hash
    summary = json.loads((run_dir / "scoring-summary.json").read_text(encoding="utf-8"))
    assert summary.get("raw_manifest_hash") == manifest_hash


# 9. score artifact changes if raw content changes
def test_9_score_artifact_changes_if_raw_content_changes(tmp_path: Path) -> None:
    # Run A
    run_a = tmp_path / "run_a"
    tx_a, _ = _setup_tx(run_a, run_id="run_a")
    tx_a.execute_raw_execution(lambda d: RunArtifactStore(d, "run_a").persist_raw_retrieval(
        query_id="Q-1", request={"query": "A"}, response={"results": []},
        transport_status=200, timestamp_utc=NOW, latency_ms=1.0, runtime_lock_sha256="0"*64
    ))
    tx_a.execute_raw_sealing()
    tx_a.execute_oracle_audit()
    rep_a = tx_a.execute_scoring()

    # Run B with different query content
    run_b = tmp_path / "run_b"
    tx_b, _ = _setup_tx(run_b, run_id="run_b")
    tx_b.execute_raw_execution(lambda d: RunArtifactStore(d, "run_b").persist_raw_retrieval(
        query_id="Q-1", request={"query": "B"}, response={"results": []},
        transport_status=200, timestamp_utc=NOW, latency_ms=1.0, runtime_lock_sha256="0"*64
    ))
    tx_b.execute_raw_sealing()
    tx_b.execute_oracle_audit()
    rep_b = tx_b.execute_scoring()

    assert rep_a.get("raw_manifest_hash") != rep_b.get("raw_manifest_hash")


# 10. 0 raw records -> PASS_NATIVE impossible
def test_10_zero_raw_records_cannot_reach_pass_native(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    tx.execute_raw_execution(lambda d: None)
    # Either raw sealing or scoring/verdict fails closed
    try:
        tx.execute_raw_sealing()
        tx.execute_oracle_audit()
        tx.execute_scoring()
        tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics(), gate_evidence={})
        verdict = tx.execute_verdict_derivation()
        assert verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE
    except TransactionError:
        pass  # Failed closed as required!


# 11. 0 scored items -> PASS_NATIVE impossible
def test_11_zero_scored_items_cannot_reach_pass_native(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    tx.execute_raw_execution(lambda d: None)
    try:
        tx.execute_raw_sealing()
        tx.execute_oracle_audit()
        tx.execute_scoring()
        tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics(), gate_evidence={})
        verdict = tx.execute_verdict_derivation()
        assert verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE
    except TransactionError:
        pass


# 12. sealed valid raw set -> audit + score allowed
def test_12_sealed_valid_raw_set_audit_and_score_allowed(tmp_path: Path) -> None:
    tx, run_dir = _setup_tx(tmp_path)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "clean query"},
            response={"results": [{"chunk_id": "chunk_1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    audit_res = tx.execute_oracle_audit()
    assert audit_res["status"] == "PASS"
    score_res = tx.execute_scoring()
    assert score_res["status"] == "PASS" or "items" in score_res
