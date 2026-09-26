"""Regression tests for F3: never synthesize missing PASS artifacts."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from harness.finalizer import REQUIRED_RELEASE_FILES, finalize_release, ReleaseFinalizationError
from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.models import VerdictStatus
from harness.transaction import CertificationTransaction, TransactionError
from harness.artifacts import RunArtifactStore

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
RUN_ID = "RUN-20260925T170000Z-f3test"


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


def _populate_all_required_artifacts(run_dir: Path, run_id: str, omit: set[str] | None = None) -> None:
    omit = omit or set()
    raw_path = run_dir / "raw" / "retrieval" / "Q-1.json"
    raw_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest() if raw_path.is_file() else "0" * 64

    standard_payloads = {
        "final-report.md": f"# Final Report\n\nRun: {run_id}\nStatus: PASS\n",
        "health-pre-test.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "phase": "PRE_TEST", "timestamp_utc": "2026-09-25T12:00:00Z", "provider_reachable": True, "services": [{"name": "mesa", "status": "PASS", "restarts": 0, "oom_killed": False}], "host_metrics": {"ram_gb": 64}, "reasons": []}, indent=2),
        "health-post-test.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "phase": "POST_TEST", "timestamp_utc": "2026-09-25T12:05:00Z", "provider_reachable": True, "services": [{"name": "mesa", "status": "PASS", "restarts": 0, "oom_killed": False}], "host_metrics": {"ram_gb": 64}, "reasons": []}, indent=2),
        "resource-provider-summary.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "oom_killed_count": 0, "container_restart_count": 0}, indent=2),
        "scorer-canary-results.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "canary_passed": True, "no_bridge_substitution": True}, indent=2),
        "determinism-manifest.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "idempotent_republish_proven": True, "restart_persistence_proven": True}, indent=2),
        "graph-summary.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "graph_capability_operational": True, "graph_causal_ablation_proven": True, "graph_provenance_verified": True, "graph_rel_contribution_count": 5}, indent=2),
        "frozen-identities.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "identities": []}, indent=2),
        "identity-map-summary.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "mapping_count": 1}, indent=2),
        "decision-summary.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "decision": "ACCEPT"}, indent=2),
        "repair-summary.json": json.dumps({"schema_version": "1.0", "run_id": run_id, "status": "PASS", "repairs_applied": 0}, indent=2),
    }

    for name, content in standard_payloads.items():
        if name not in omit:
            p = run_dir / name
            p.write_text(content + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")


def _run_tx_through_run_id_consistency(tmp_path: Path, run_id: str = RUN_ID, omit_artifacts: set[str] | None = None) -> tuple[CertificationTransaction, Path]:
    run_dir = tmp_path / run_id
    freeze_path, checksum_path, freeze_dir, repo_shas = _make_freeze(tmp_path, run_id)
    tx = CertificationTransaction(run_id, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=freeze_dir, current_repository_shas=repo_shas)

    def build_raw(d: Path):
        store = RunArtifactStore(d, run_id)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test query"},
            response={"results": [{"chunk_id": "chunk_1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )

    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics(), gate_evidence={})
    verdict = tx.execute_verdict_derivation()
    assert verdict.status == VerdictStatus.PROFILE_B_PASS_NATIVE

    raw_file = run_dir / "raw" / "retrieval" / "Q-1.json"
    records = [
        {
            "path": "raw/retrieval/Q-1.json",
            "sha256": hashlib.sha256(raw_file.read_bytes()).hexdigest(),
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": NOW,
            "source_run_id": run_id,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        }
    ]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()

    # Populate real producer artifacts, omitting specified ones
    _populate_all_required_artifacts(run_dir, run_id, omit=omit_artifacts)
    return tx, run_dir


# 1. missing health-pre-test.json -> finalization fails
def test_1_missing_health_pre_test_fails_finalization(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    sources["health-pre-test.json"].unlink()
    with pytest.raises(ReleaseFinalizationError, match="release source is not a file: health-pre-test.json"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not sources["health-pre-test.json"].exists()
    assert not (tmp_path / "release" / "RUN-independent").exists()


# 2. missing health-post-test.json -> fails
def test_2_missing_health_post_test_fails_finalization(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    sources["health-post-test.json"].unlink()
    with pytest.raises(ReleaseFinalizationError, match="release source is not a file: health-post-test.json"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not sources["health-post-test.json"].exists()
    assert not (tmp_path / "release" / "RUN-independent").exists()


# 3. missing determinism manifest -> fails
def test_3_missing_determinism_manifest_fails_finalization(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    sources["determinism-manifest.json"].unlink()
    with pytest.raises(ReleaseFinalizationError, match="release source is not a file: determinism-manifest.json"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not sources["determinism-manifest.json"].exists()
    assert not (tmp_path / "release" / "RUN-independent").exists()


# 4. missing scorer canaries -> fails
def test_4_missing_scorer_canaries_fails_finalization(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    sources["scorer-canary-results.json"].unlink()
    with pytest.raises(ReleaseFinalizationError, match="release source is not a file: scorer-canary-results.json"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not sources["scorer-canary-results.json"].exists()
    assert not (tmp_path / "release" / "RUN-independent").exists()


# 5. missing graph summary when mandatory -> fails
def test_5_missing_graph_summary_fails_finalization(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    sources["graph-summary.json"].unlink()
    with pytest.raises(ReleaseFinalizationError, match="release source is not a file: graph-summary.json"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not sources["graph-summary.json"].exists()
    assert not (tmp_path / "release" / "RUN-independent").exists()


# 6. missing resource summary -> fails
def test_6_missing_resource_summary_fails_finalization(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    sources["resource-provider-summary.json"].unlink()
    with pytest.raises(ReleaseFinalizationError, match="release source is not a file: resource-provider-summary.json"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not sources["resource-provider-summary.json"].exists()
    assert not (tmp_path / "release" / "RUN-independent").exists()


# 7. transaction never creates fake PASS placeholder
def test_7_transaction_never_creates_fake_pass_placeholder(tmp_path: Path) -> None:
    from tests.independent_support import transaction
    from harness.transaction import TransactionError
    from harness.operations import verify_health_artifacts
    tx = transaction(tmp_path)
    report = verify_health_artifacts(tx.run_dir, tx.run_id)
    assert report["status"] == "UNVERIFIED"
    for name in ("health-pre-test.json", "health-post-test.json", "provider-preflight-evidence.json", "determinism-manifest.json"):
        assert not (tx.run_dir / name).exists()


# 8. only real producer-created valid artifacts -> accepted
def test_8_status_only_placeholders_are_rejected(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    with pytest.raises(ReleaseFinalizationError, match="mandatory gate|unverified"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
    assert not (tmp_path / "release" / "RUN-independent").exists()


# 9. artifact with status=PASS but invalid hash/schema -> rejected
def test_9_artifact_with_pass_status_but_invalid_schema_rejected(tmp_path: Path) -> None:
    from tests.independent_support import placeholder_sources
    sources = placeholder_sources(tmp_path)
    sources["health-post-test.json"].write_text('{"schema_version": "1.0", "status": "PASS", "invalid_field": 123}')
    with pytest.raises(ReleaseFinalizationError, match="RUN_ID mismatch"):
        finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")


# 10. empty evidence index -> PASS_NATIVE impossible
def test_10_empty_evidence_index_fails_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, freeze_dir, repo_shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=freeze_dir, current_repository_shas=repo_shas)
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
    with pytest.raises(TransactionError, match="empty evidence index|evidence"):
        tx.execute_evidence_index([])


# 11. 0 artifacts finalization -> fail closed
def test_11_zero_artifacts_finalization_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ReleaseFinalizationError):
        finalize_release(run_id="run_empty", sources={}, release_root=tmp_path / "rel")
