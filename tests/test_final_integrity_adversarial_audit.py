"""Adversarial self-audit suite (A1-A20) verifying all 20 phase-boundary attacks."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from harness.answer_scorer import score_answer
from harness.artifacts import AnswerExecutionCapture, RunArtifactStore
from harness.finalizer import REQUIRED_RELEASE_FILES, finalize_release, ReleaseFinalizationError
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
from harness.oracle import audit_oracle_surfaces
from harness.transaction import CertificationTransaction, TransactionError, TransactionPhase

RUN_ID = "RUN-20260925T190000Z-adv"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


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
        "B10": {"answerable_mrr": 1.0, "answerable_recall_at_5": 1.0, "rel_complete_evidence_at_5": 1.0, "single_hop_recall_at_5": 1.0, "tenant_leakage": 0},
        "B11": {"graph_capability_operational": True, "graph_causal_ablation_proven": True, "graph_provenance_verified": True, "graph_rel_contribution_count": 5},
        "B12": {"answerable_pass_rate": 1.0, "fabricated_evidence_chunk_ids": 0, "no_answer_pass_rate": 1.0, "unsupported_material_claim_rate": 0},
        "B13": {"catastrophic_resource_failure": 0, "oom_killed_count": 0, "resource_usage_recorded": True},
        "B14": {"evidence_integrity_verified": True, "post_freeze_mutations": 0},
    }


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


# A1 — Zero-query certification attempt -> PASS_NATIVE impossible
def test_a01_zero_query_certification_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    tx.execute_raw_execution(lambda d: None)
    tx.execute_raw_sealing()
    with pytest.raises(TransactionError, match="oracle audit failed.*empty_raw_execution|0 raw records"):
        tx.execute_oracle_audit()


# A2 — Zero-score certification attempt -> PASS_NATIVE impossible
def test_a02_zero_score_certification_fails(tmp_path: Path) -> None:
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
    with pytest.raises(TransactionError, match="scoring failed.*0 scored items"):
        tx.execute_scoring(scoring_fn=lambda r: None)


# A3 — Zero-evidence certification attempt -> PASS_NATIVE impossible
def test_a03_zero_evidence_certification_fails(tmp_path: Path) -> None:
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
    with pytest.raises(TransactionError, match="empty evidence index"):
        tx.execute_evidence_index([])


# A4 — Raw oracle leak with empty caller audit surface -> detected & rejected
def test_a04_raw_oracle_leak_empty_caller_audit_surface(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw_leak(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={"query": "test with expected_answer leak"},
            response={"results": [{"chunk_id": "c1"}]},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="0" * 64,
        )
    tx.execute_raw_execution(build_raw_leak)
    tx.execute_raw_sealing()
    # Empty caller surface passed: auditor must still audit sealed raw files and detect the leak!
    with pytest.raises(TransactionError, match="oracle audit failed"):
        tx.execute_oracle_audit(oracle_surfaces=[])


# A5 — Oracle leak through arbitrary dict key/nested value/error string -> detected
def test_a05_oracle_leak_nested_key_or_error() -> None:
    surfaces = {
        "nested/deep.json": {
            "outer": {
                "middle": {
                    "error_message": "leaked forbidden token: expected_answer active"
                }
            }
        }
    }
    report = audit_oracle_surfaces(surfaces, run_id=RUN_ID)
    assert report["status"] == "FAIL"
    assert report["finding_count"] > 0


# A6 — Raw manifest mutated after audit -> scoring rejects
def test_a06_raw_manifest_mutated_after_audit_rejected(tmp_path: Path) -> None:
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

    # Mutate raw file after audit
    raw_file = run_dir / "raw" / "retrieval" / "Q-1.json"
    raw_file.chmod(0o644)
    raw_file.write_text('{"tampered": true}\n', encoding="utf-8")

    with pytest.raises(TransactionError, match="scoring failed.*seal|scoring failed.*modified"):
        tx.execute_scoring()


# A7 — Alternate caller scoring record passed to gate evaluation -> rejected
def test_a07_alternate_caller_scoring_record_rejected(tmp_path: Path) -> None:
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
    def failing_scorer(raw_payload: dict):
        return {"query_id": "Q-1", "status": "FAIL", "lane": "retrieval", "recall_at_5": 0.0, "mrr": 0.0}
    tx.execute_scoring(scoring_fn=failing_scorer)

    # Caller tries to pass passing gate_metrics to override real failing score
    gate_results = tx.execute_gate_evaluation(gate_metrics={"B10": {"answerable_mrr": 1.0, "answerable_recall_at_5": 1.0}})
    b10_res = next((g for g in gate_results if g.gate_id == "B10"), None)
    assert b10_res is not None
    # Must derive from authoritative score artifact, ignoring caller's fake 1.0!
    assert b10_res.status.value == "FAIL"


# A8 — Fake gate metrics passed by caller -> rejected (authoritative derived only)
def test_a08_fake_gate_metrics_rejected(tmp_path: Path) -> None:
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
    def failing_scorer(raw_payload: dict):
        return {"query_id": "Q-1", "status": "FAIL", "lane": "retrieval", "recall_at_5": 0.1, "mrr": 0.1}
    tx.execute_scoring(scoring_fn=failing_scorer)

    # Fake metrics claiming 0.999
    gate_results = tx.execute_gate_evaluation(gate_metrics={"B10": {"answerable_recall_at_5": 0.999, "answerable_mrr": 0.999}})
    b10_res = next((g for g in gate_results if g.gate_id == "B10"), None)
    assert b10_res.observed["answerable_recall_at_5"] != 0.999
    assert b10_res.status.value == "FAIL"


# A9 — Fake gate evidence passed by caller -> rejected (verified existence only)
def test_a09_fake_gate_evidence_rejected(tmp_path: Path) -> None:
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

    # Pass non-existent file in gate_evidence
    gate_results = tx.execute_gate_evaluation(gate_evidence={"B10": ["non_existent_fake_evidence.json"]})
    b10_res = next((g for g in gate_results if g.gate_id == "B10"), None)
    # Must fail because evidence does not exist on disk
    assert b10_res.status.value == "FAIL"


# A10 — Hard gate FAIL serialized as PASS -> finalizer rejects
def test_a10_hard_gate_fail_serialized_as_pass(tmp_path: Path) -> None:
    sources = {}
    for name in REQUIRED_RELEASE_FILES:
        p = tmp_path / name
        if name == "final-report.md":
            p.write_text(f"# Final Report\n\nRun: {RUN_ID}\n", encoding="utf-8")
        elif name == "gate-results.json":
            # Tampered: gate B10 has status FAIL, but final_verdict claims PROFILE_B_PASS_NATIVE
            p.write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "run_id": RUN_ID,
                    "final_verdict": "PROFILE_B_PASS_NATIVE",
                    "mandatory_gate_ids": ["B10"],
                    "gates": [{"gate_id": "B10", "hard": True, "status": "FAIL", "requirements": {}, "observed": {}}],
                }),
                encoding="utf-8",
            )
        else:
            p.write_text(json.dumps({"schema_version": "1.0", "run_id": RUN_ID, "status": "PASS"}), encoding="utf-8")
        sources[name] = p

    with pytest.raises(ReleaseFinalizationError, match="hard gate.*status FAIL.*cannot promote PASS"):
        finalize_release(run_id=RUN_ID, sources=sources, release_root=tmp_path / "rel")


# A11 — Missing health-pre-test.json -> release finalization fails closed
def test_a11_missing_health_pre_test_fails_finalization(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(query_id="Q-1", request={"query": "test"}, response={"results": [{"chunk_id": "c1"}]}, transport_status=200, timestamp_utc=NOW, latency_ms=10.0, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    _populate_supplementary_release_files(run_dir, RUN_ID)
    tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics())
    tx.execute_verdict_derivation()
    raw_path = run_dir / "raw" / "retrieval" / "Q-1.json"
    records = [{"path": "raw/retrieval/Q-1.json", "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(), "producer": "harness", "phase": "test", "timestamp_utc": NOW, "source_run_id": RUN_ID, "immutable": True, "sealed": True, "artifact_type": "evidence"}]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()
    tx.execute_health_verification()

    # Remove health-pre-test.json
    (run_dir / "health-pre-test.json").unlink()

    with pytest.raises(TransactionError, match="missing required release artifacts"):
        tx.execute_release_finalization(tmp_path / "rel")


# A12 — Missing determinism manifest -> release finalization fails closed
def test_a12_missing_determinism_manifest_fails_finalization(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(query_id="Q-1", request={"query": "test"}, response={"results": [{"chunk_id": "c1"}]}, transport_status=200, timestamp_utc=NOW, latency_ms=10.0, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    _populate_supplementary_release_files(run_dir, RUN_ID)
    tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics())
    tx.execute_verdict_derivation()
    raw_path = run_dir / "raw" / "retrieval" / "Q-1.json"
    records = [{"path": "raw/retrieval/Q-1.json", "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(), "producer": "harness", "phase": "test", "timestamp_utc": NOW, "source_run_id": RUN_ID, "immutable": True, "sealed": True, "artifact_type": "evidence"}]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()
    tx.execute_health_verification()

    # Remove determinism-manifest.json
    (run_dir / "determinism-manifest.json").unlink()

    with pytest.raises(TransactionError, match="missing required release artifacts"):
        tx.execute_release_finalization(tmp_path / "rel")


# A13 — Missing scorer canaries -> release finalization fails closed
def test_a13_missing_scorer_canaries_fails_finalization(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(query_id="Q-1", request={"query": "test"}, response={"results": [{"chunk_id": "c1"}]}, transport_status=200, timestamp_utc=NOW, latency_ms=10.0, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    _populate_supplementary_release_files(run_dir, RUN_ID)
    tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics())
    tx.execute_verdict_derivation()
    raw_path = run_dir / "raw" / "retrieval" / "Q-1.json"
    records = [{"path": "raw/retrieval/Q-1.json", "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(), "producer": "harness", "phase": "test", "timestamp_utc": NOW, "source_run_id": RUN_ID, "immutable": True, "sealed": True, "artifact_type": "evidence"}]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()
    tx.execute_health_verification()

    # Remove scorer-canary-results.json
    (run_dir / "scorer-canary-results.json").unlink()

    with pytest.raises(TransactionError, match="missing required release artifacts"):
        tx.execute_release_finalization(tmp_path / "rel")


# A14 — Synthetic PASS placeholder injected -> rejected / cannot promote
def test_a14_synthetic_pass_placeholder_injected_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(query_id="Q-1", request={"query": "test"}, response={"results": [{"chunk_id": "c1"}]}, transport_status=200, timestamp_utc=NOW, latency_ms=10.0, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()
    _populate_supplementary_release_files(run_dir, RUN_ID)
    tx.execute_gate_evaluation(gate_metrics=_pass_all_gates_metrics())
    tx.execute_verdict_derivation()
    raw_path = run_dir / "raw" / "retrieval" / "Q-1.json"
    records = [{"path": "raw/retrieval/Q-1.json", "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(), "producer": "harness", "phase": "test", "timestamp_utc": NOW, "source_run_id": RUN_ID, "immutable": True, "sealed": True, "artifact_type": "evidence"}]
    tx.execute_evidence_index(records)
    tx.execute_run_id_consistency()
    tx.execute_health_verification()

    # Overwrite health-pre-test.json with empty or invalid content
    (run_dir / "health-pre-test.json").write_text("", encoding="utf-8")

    with pytest.raises(TransactionError):
        tx.execute_release_finalization(tmp_path / "rel")


# A15 — Unsupported one-token material claim in answer -> UNRESOLVED/FAIL
def test_a15_unsupported_one_token_material_claim() -> None:
    imap = IdentityMap()
    imap.add_mapping("M-1", "S-1")
    gt = GroundTruthItem(
        query_id="Q-15",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[RequiredFact(fact_id="f1", claim="Ceza 5 yıldır", supported_by=[ExactSourceSpan(source_chunk_id="S-1", exact_text="Ceza 5 yıldır")])],
        acceptable_answer_patterns=[AnswerPattern(mode=PatternMode.LITERAL, value="ceza 5 yıl", fact_ids=["f1"])],
    )
    resp = AnswerResponse(
        answer="Ceza 5 yıldır sürgün",
        evidence_chunk_ids=["M-1"],
        claims=[AnswerClaim(fact_ids=["f1"], text="Ceza 5 yıldır sürgün", evidence_chunk_ids=["M-1"])],
    )
    score = score_answer(gt, resp, ["M-1"], imap)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# A16 — Unsupported monetary hallucination in answer -> UNRESOLVED/FAIL
def test_a16_unsupported_monetary_hallucination() -> None:
    imap = IdentityMap()
    imap.add_mapping("M-1", "S-1")
    gt = GroundTruthItem(
        query_id="Q-16",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[RequiredFact(fact_id="f1", claim="Ceza 5 yıldır", supported_by=[ExactSourceSpan(source_chunk_id="S-1", exact_text="Ceza 5 yıldır")])],
        acceptable_answer_patterns=[AnswerPattern(mode=PatternMode.LITERAL, value="ceza 5 yıl", fact_ids=["f1"])],
    )
    resp = AnswerResponse(
        answer="Ceza 5 yıldır 500 TL",
        evidence_chunk_ids=["M-1"],
        claims=[AnswerClaim(fact_ids=["f1"], text="Ceza 5 yıldır 500 TL", evidence_chunk_ids=["M-1"])],
    )
    score = score_answer(gt, resp, ["M-1"], imap)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# A17 — Negated required fact in answer -> FAIL
def test_a17_negated_required_fact() -> None:
    imap = IdentityMap()
    imap.add_mapping("M-1", "S-1")
    gt = GroundTruthItem(
        query_id="Q-17",
        query_class="SINGLE_DIRECT",
        question="Ceza nedir?",
        expected_source_chunk_ids=["S-1"],
        required_facts=[RequiredFact(fact_id="f1", claim="Ceza 5 yıldır", supported_by=[ExactSourceSpan(source_chunk_id="S-1", exact_text="Ceza 5 yıldır")])],
        acceptable_answer_patterns=[AnswerPattern(mode=PatternMode.LITERAL, value="ceza 5 yıl", fact_ids=["f1"])],
    )
    resp = AnswerResponse(
        answer="Ceza 5 yıl değildir",
        evidence_chunk_ids=["M-1"],
        claims=[AnswerClaim(fact_ids=["f1"], text="Ceza 5 yıl değildir", evidence_chunk_ids=["M-1"])],
    )
    score = score_answer(gt, resp, ["M-1"], imap)
    assert score.status == "FAIL"


# A18 — Score artifact bound to another raw manifest hash -> gate eval rejects
def test_a18_score_artifact_bound_to_different_raw_manifest_hash(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(query_id="Q-1", request={"query": "test"}, response={"results": [{"chunk_id": "c1"}]}, transport_status=200, timestamp_utc=NOW, latency_ms=10.0, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    tx.execute_scoring()

    # Modify scoring summary raw_manifest_hash to alien hash and resigned
    summary_path = run_dir / "scoring-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["raw_manifest_hash"] = "f" * 64
    summary_bytes = json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    summary_path.chmod(0o644)
    summary_path.write_bytes(summary_bytes)
    summary_path.chmod(0o444)
    new_sha = hashlib.sha256(summary_bytes).hexdigest()
    sidecar = summary_path.with_suffix(".json.SHA256")
    sidecar.write_text(f"{new_sha}  scoring-summary.json\n", encoding="utf-8")

    with pytest.raises(TransactionError, match="score artifact raw manifest hash mismatch"):
        tx.execute_gate_evaluation()


# A19 — Lifecycle stage skipped (e.g., scoring skipped, gates run) -> rejected
def test_a19_lifecycle_stage_skipped_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(query_id="Q-1", request={"query": "test"}, response={"results": [{"chunk_id": "c1"}]}, transport_status=200, timestamp_utc=NOW, latency_ms=10.0, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    # Skip tx.execute_scoring() and jump to execute_gate_evaluation()!
    with pytest.raises(TransactionError, match="Out-of-order phase execution|phase sequence violation"):
        tx.execute_gate_evaluation()


# A20 — Caller forces final_verdict="PROFILE_B_PASS_NATIVE" on failed run -> rejected
def test_a20_caller_forced_final_verdict_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    freeze_path, checksum_path, repo_root, shas = _make_freeze(tmp_path, RUN_ID)
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(freeze_path, checksum_path, repository_root=repo_root, current_repository_shas=shas)
    def build_raw(d: Path):
        store = RunArtifactStore(d, RUN_ID)
        store.persist_raw_retrieval(query_id="Q-1", request={"query": "test"}, response={"results": [{"chunk_id": "c1"}]}, transport_status=200, timestamp_utc=NOW, latency_ms=10.0, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(build_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    def failing_scorer(raw_payload: dict):
        return {"query_id": "Q-1", "status": "FAIL", "lane": "retrieval", "recall_at_5": 0.0, "mrr": 0.0}
    tx.execute_scoring(scoring_fn=failing_scorer)
    tx.execute_gate_evaluation()

    # Caller tries to pass final_verdict="PROFILE_B_PASS_NATIVE" to verdict derivation -> TypeError
    with pytest.raises(TypeError):
        tx.execute_verdict_derivation(final_verdict="PROFILE_B_PASS_NATIVE")  # type: ignore

    # Authoritative derivation computes verdict from actual gate evaluations -> FAIL / BLOCKED
    verdict = tx.execute_verdict_derivation()
    assert verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE
