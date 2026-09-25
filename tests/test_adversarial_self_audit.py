"""Adversarial self-audit suite (A1-A20) for MESA E2E Certification."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from harness.answer_scorer import score_answer
from harness.artifacts import (
    ArtifactOrderError,
    ImmutableArtifactError,
    RunArtifactStore,
)
from harness.evidence import build_evidence_index, validate_run_id_consistency
from harness.finalizer import finalize_release, ReleaseFinalizationError
from harness.freeze import (
    create_contract_freeze,
    verify_contract_freeze,
    FreezeStatus,
    MANDATORY_MATERIAL_CATEGORIES,
    MANDATORY_REPOSITORIES,
)
from harness.gates import (
    GateConfig,
    GateDefinition,
    evaluate_threshold_gate,
    load_gate_config,
)
from harness.models import (
    AnswerClaim,
    AnswerPattern,
    AnswerResponse,
    ExactSourceSpan,
    ExecutionStatus,
    GateResult,
    GateStatus,
    GroundTruthItem,
    PatternMode,
    RequiredFact,
    ScoringStatus,
    VerdictStatus,
)
from harness.identity import IdentityMap
from harness.oracle import audit_oracle_surfaces
from harness.transaction import (
    CertificationTransaction,
    TransactionError,
)
from harness.verdict import derive_production_verdict, evaluate_final_verdict


RUN_ID = "RUN-20260925T150000Z-audit"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


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
        created_at=NOW,
    )
    return freeze_path, checksum_path, repository_shas


# =========================================================================
# A1: Empty/partial freeze + correct sidecar
# =========================================================================
def test_a01_partial_freeze_with_valid_sha(tmp_path: Path) -> None:
    freeze_path = tmp_path / "contract-freeze.json"
    checksum_path = tmp_path / "contract-freeze.SHA256"
    # Valid schema, valid run_id, valid JSON, but missing categories and repositories
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "created_at_utc": NOW.isoformat(),
        "repository_shas": {"MESA": "a" * 40},  # Missing MESA_Data, MESA_E2E_Certification
        "materials": [],  # Missing mandatory materials
    }
    content = json.dumps(payload, indent=2) + "\n"
    freeze_path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  contract-freeze.json\n", encoding="utf-8")

    result = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={"MESA": "a" * 40},
    )
    assert result.status != FreezeStatus.PASS
    assert result.status in {
        FreezeStatus.FREEZE_MISSING_REQUIRED_MATERIAL,
        FreezeStatus.FREEZE_REPOSITORY_IDENTITY_MISSING,
        FreezeStatus.FREEZE_INVALID,
    }


# =========================================================================
# A2: Missing repository SHA
# =========================================================================
def test_a02_missing_repository_sha(tmp_path: Path) -> None:
    freeze_path = tmp_path / "contract-freeze.json"
    checksum_path = tmp_path / "contract-freeze.SHA256"
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "created_at_utc": NOW.isoformat(),
        "repository_shas": {
            "MESA": "a" * 40,
            "MESA_Data": "",  # Empty SHA
            "MESA_E2E_Certification": "c" * 40,
        },
        "materials": [
            {"category": cat, "path": f"{cat}.txt", "sha256": "a" * 64}
            for cat in sorted(MANDATORY_MATERIAL_CATEGORIES)
        ],
    }
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  contract-freeze.json\n", encoding="utf-8")

    result = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40},
    )
    assert result.status != FreezeStatus.PASS


# =========================================================================
# A3: Missing mandatory frozen material
# =========================================================================
def test_a03_missing_mandatory_frozen_material(tmp_path: Path) -> None:
    freeze_path = tmp_path / "contract-freeze.json"
    checksum_path = tmp_path / "contract-freeze.SHA256"
    # Include all repos, but omit 'prompts' category
    cats = [c for c in sorted(MANDATORY_MATERIAL_CATEGORIES) if c != "prompts"]
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "created_at_utc": NOW.isoformat(),
        "repository_shas": {
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
        "materials": [{"category": cat, "path": f"{cat}.txt", "sha256": "a" * 64} for cat in cats],
    }
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  contract-freeze.json\n", encoding="utf-8")

    result = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40},
    )
    assert result.status == FreezeStatus.FREEZE_MISSING_REQUIRED_MATERIAL


# =========================================================================
# A4: PASS verdict containing hard-gate FAIL
# =========================================================================
def test_a04_pass_verdict_containing_fail_hard_gate(tmp_path: Path) -> None:
    from harness.finalizer import REQUIRED_RELEASE_FILES

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in REQUIRED_RELEASE_FILES:
        p = source_dir / name
        if name == "final-report.md":
            p.write_text(f"# Report\n\nRun: {RUN_ID}\nStatus: PASS\n", encoding="utf-8")
        elif name == "gate-results.json":
            # Tampered: gate is FAIL, but top claims PASS
            p.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "run_id": RUN_ID,
                        "status": "PASS",
                        "final_verdict": "PROFILE_B_PASS_NATIVE",
                        "gates": [{"gate_id": "B10", "hard": True, "status": "FAIL"}],
                    }
                ),
                encoding="utf-8",
            )
        else:
            p.write_text(json.dumps({"schema_version": "1.0", "run_id": RUN_ID, "status": "PASS"}), encoding="utf-8")

    with pytest.raises(ReleaseFinalizationError, match="hard gate.*status FAIL|tampered final_verdict"):
        finalize_release(
            run_id=RUN_ID,
            sources={name: source_dir / name for name in REQUIRED_RELEASE_FILES},
            release_root=tmp_path / "release",
        )


# =========================================================================
# A5: Tampered final_verdict string
# =========================================================================
def test_a05_tampered_final_verdict(tmp_path: Path) -> None:
    from harness.finalizer import REQUIRED_RELEASE_FILES

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in REQUIRED_RELEASE_FILES:
        p = source_dir / name
        if name == "final-report.md":
            p.write_text(f"# Report\n\nRun: {RUN_ID}\nStatus: PASS\n", encoding="utf-8")
        elif name == "gate-results.json":
            p.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "run_id": RUN_ID,
                        "status": "PASS",
                        "final_verdict": "PROFILE_B_PASS_FORCED_BY_ATTACKER",
                        "gates": [{"gate_id": "B10", "hard": True, "status": "PASS"}],
                    }
                ),
                encoding="utf-8",
            )
        else:
            p.write_text(json.dumps({"schema_version": "1.0", "run_id": RUN_ID, "status": "PASS"}), encoding="utf-8")

    with pytest.raises(ReleaseFinalizationError, match="invalid final verdict"):
        finalize_release(
            run_id=RUN_ID,
            sources={name: source_dir / name for name in REQUIRED_RELEASE_FILES},
            release_root=tmp_path / "release",
        )


# =========================================================================
# A6: Raw file added after oracle audit
# =========================================================================
def test_a06_raw_file_added_after_oracle_audit(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    tx.execute_freeze(freeze_path, checksum_path, repository_root=tmp_path, current_repository_shas=shas)

    def make_raw(d: Path) -> None:
        tx.store.persist_raw_retrieval(
            query_id="Q1",
            request={"query": "test"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="a" * 64,
        )

    tx.execute_raw_execution(make_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit([])

    # Scenario A: attacker drops an unsealed raw file
    raw_ans = run_dir / "raw" / "answers"
    raw_ans.mkdir(parents=True, exist_ok=True)
    sneaky_file = raw_ans / "sneaky.json"
    sneaky_file.write_text(json.dumps({"answer": "leaked"}), encoding="utf-8")

    with pytest.raises(ArtifactOrderError, match="raw artifact or seal is missing"):
        tx.store.compute_raw_manifest()

    # Scenario B: attacker creates a valid sealed file -> manifest hash diverges from audited hash
    sneaky_file.unlink()
    tx.store.persist_raw_retrieval(
        query_id="Q2",
        request={"query": "sneaky"},
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=10.0,
        runtime_lock_sha256="a" * 64,
    )
    current_manifest = tx.store.compute_raw_manifest()
    assert current_manifest["manifest_hash"] != tx.audited_manifest_hash


# =========================================================================
# A7: Raw file modified after oracle audit
# =========================================================================
def test_a07_raw_file_modified_after_oracle_audit(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    tx.execute_freeze(freeze_path, checksum_path, repository_root=tmp_path, current_repository_shas=shas)

    def make_raw(d: Path) -> None:
        tx.store.persist_raw_retrieval(
            query_id="Q1",
            request={"query": "test"},
            response={"results": []},
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=10.0,
            runtime_lock_sha256="a" * 64,
        )

    tx.execute_raw_execution(make_raw)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit([])

    # Tamper with Q1.json without updating sidecar
    q1_path = run_dir / "raw" / "retrieval" / "Q1.json"
    q1_path.write_text(json.dumps({"query_id": "Q1", "tampered": True}), encoding="utf-8")

    with pytest.raises(ImmutableArtifactError, match="sealed artifact mutated"):
        tx.store.compute_raw_manifest()


# =========================================================================
# A8: Leak gold ID through arbitrary JSON value
# =========================================================================
def test_a08_leak_gold_id_through_arbitrary_json_value() -> None:
    surfaces = {
        "complex_trace": {
            "execution": {
                "steps": [
                    {"step": 1, "note": "fetching"},
                    {"step": 2, "details": {"inner_note": "Found GOLD_SECRET_CHUNK_999 in cache"}},
                ]
            }
        }
    }
    report = audit_oracle_surfaces(
        surfaces,
        known_oracle_values={"GOLD_SECRET_CHUNK_999"},
    )
    assert report["status"] == "FAIL"
    assert any("GOLD_SECRET_CHUNK_999" in str(f) for f in report["findings"])


# =========================================================================
# A9: Negated required fact such as "değildir"
# =========================================================================
def test_a09_negated_required_fact_fails_scoring() -> None:
    gt = GroundTruthItem(
        query_id="Q01",
        query_class="SINGLE_DIRECT",
        question="Kanun uygulanır mı?",
        is_answerable=True,
        expected_source_chunk_ids=["S-1"],
        required_facts=[
            RequiredFact(
                fact_id="f1",
                claim="kanun hükmü uygulanır",
                supported_by=[ExactSourceSpan(source_chunk_id="S-1", exact_text="kanun hükmü uygulanır")],
            )
        ],
        acceptable_answer_patterns=[
            AnswerPattern(mode=PatternMode.LITERAL, value="kanun hükmü uygulanır", fact_ids=["f1"])
        ],
    )
    id_map = IdentityMap()
    id_map.add_mapping("M-1", "S-1")
    # The answer states the opposite using negation 'değildir'
    answer_obj = AnswerResponse(
        answer="Bu durumda ilgili kanun hükmü uygulanır değildir.",
        evidence_chunk_ids=["M-1"],
        insufficient_evidence=False,
        claims=[
            AnswerClaim(
                fact_ids=["f1"],
                text="Bu durumda ilgili kanun hükmü uygulanır değildir.",
                evidence_chunk_ids=["M-1"],
            )
        ],
    )
    score = score_answer(gt, answer_obj, ["M-1"], id_map)
    assert score.status is not ScoringStatus.PASS
    assert score.status == "FAIL"


# =========================================================================
# A10: Correct fact + unsupported hallucination
# =========================================================================
def test_a10_correct_fact_plus_unsupported_hallucination_fails() -> None:
    gt = GroundTruthItem(
        query_id="Q02",
        query_class="SINGLE_DIRECT",
        question="Yargıtay kararı ne yöndedir?",
        is_answerable=True,
        expected_source_chunk_ids=["S-1"],
        required_facts=[
            RequiredFact(
                fact_id="f1",
                claim="davanın reddi gerekir",
                supported_by=[ExactSourceSpan(source_chunk_id="S-1", exact_text="davanın reddi gerekir")],
            )
        ],
        acceptable_answer_patterns=[
            AnswerPattern(mode=PatternMode.LITERAL, value="davanın reddi gerekir", fact_ids=["f1"])
        ],
    )
    id_map = IdentityMap()
    id_map.add_mapping("M-1", "S-1")
    # Contains required fact, but claim has 3+ hallucinated words not supported by chunks
    answer_obj = AnswerResponse(
        answer="Davanın reddi gerekir ve ayrıca fail yüz milyon lira tazminat cezasına çarptırılmıştır.",
        evidence_chunk_ids=["M-1"],
        insufficient_evidence=False,
        claims=[
            AnswerClaim(
                fact_ids=["f1"],
                text="Davanın reddi gerekir ve ayrıca fail yüz milyon lira tazminat cezasına çarptırılmıştır.",
                evidence_chunk_ids=["M-1"],
            )
        ],
    )
    score = score_answer(gt, answer_obj, ["M-1"], id_map)
    assert score.status in {"UNRESOLVED", "FAIL"}
    assert score.status != "PASS"


# =========================================================================
# A11: Substantive answer + YETERSİZ KANIT
# =========================================================================
def test_a11_substantive_answer_plus_yetersiz_kanit_fails() -> None:
    gt = GroundTruthItem(
        query_id="Q03",
        query_class="SINGLE_DIRECT",
        question="Sözleşme geçerli midir?",
        is_answerable=True,
        expected_source_chunk_ids=["S-1"],
        required_facts=[
            RequiredFact(
                fact_id="f1",
                claim="sözleşme geçerlidir",
                supported_by=[ExactSourceSpan(source_chunk_id="S-1", exact_text="sözleşme geçerlidir")],
            )
        ],
        acceptable_answer_patterns=[
            AnswerPattern(mode=PatternMode.LITERAL, value="sözleşme geçerlidir", fact_ids=["f1"])
        ],
    )
    id_map = IdentityMap()
    id_map.add_mapping("M-1", "S-1")
    # Answer gives a substantive conclusion, but also sets insufficient_evidence=True
    answer_obj = AnswerResponse(
        answer="Sözleşme geçerlidir ancak yetersiz kanıt bulunmaktadır.",
        evidence_chunk_ids=["M-1"],
        insufficient_evidence=True,
        claims=[
            AnswerClaim(
                fact_ids=["f1"],
                text="Sözleşme geçerlidir ancak yetersiz kanıt bulunmaktadır.",
                evidence_chunk_ids=["M-1"],
            )
        ],
    )
    score = score_answer(gt, answer_obj, ["M-1"], id_map)
    assert score.status != "PASS"


# =========================================================================
# A12: Real evidence-index producer → real finalizer
# =========================================================================
def test_a12_real_evidence_index_producer_accepted_by_finalizer(tmp_path: Path) -> None:
    from harness.finalizer import REQUIRED_RELEASE_FILES

    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    art_file = run_dir / "art.json"
    art_file.write_text(json.dumps({"run_id": RUN_ID, "status": "PASS"}), encoding="utf-8")

    records = [
        {
            "path": "art.json",
            "sha256": hashlib.sha256(art_file.read_bytes()).hexdigest(),
            "producer": "harness",
            "phase": "test",
            "timestamp_utc": NOW,
            "source_run_id": RUN_ID,
            "immutable": True,
            "sealed": True,
            "artifact_type": "evidence",
        }
    ]
    build_evidence_index(
        run_dir=run_dir,
        output_path=run_dir / "evidence-index.json",
        records=records,
        run_id=RUN_ID,
        created_at=NOW,
    )

    # Populate remaining release files with valid PASS metadata
    categories = sorted(MANDATORY_MATERIAL_CATEGORIES)
    for name in REQUIRED_RELEASE_FILES:
        p = run_dir / name
        if not p.is_file():
            if name == "final-report.md":
                p.write_text(f"# Report\n\nRun: {RUN_ID}\nStatus: PASS\n", encoding="utf-8")
            elif name == "gate-results.json":
                p.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "run_id": RUN_ID,
                            "final_verdict": "PROFILE_B_PASS_NATIVE",
                            "mandatory_gate_ids": ["B10"],
                            "gates": [
                                {
                                    "gate_id": "B10",
                                    "hard": True,
                                    "status": "PASS",
                                    "requirements": {"m": {"operator": "gte", "value": 0.7}},
                                    "observed": {"m": 0.85},
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
            elif name == "contract-freeze.json":
                p.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "run_id": RUN_ID,
                            "status": "PASS",
                            "freeze_valid": True,
                            "repository_shas": {
                                "MESA": "a" * 40,
                                "MESA_Data": "b" * 40,
                                "MESA_E2E_Certification": "c" * 40,
                            },
                            "materials": [
                                {"category": cat, "path": f"{cat}.txt", "sha256": "0" * 64}
                                for cat in categories
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
            elif name == "run_manifest.json":
                p.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "run_id": RUN_ID,
                            "status": "PASS_NATIVE",
                            "lifecycle_valid": True,
                        }
                    ),
                    encoding="utf-8",
                )
            elif name == "determinism-manifest.json":
                p.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "run_id": RUN_ID,
                            "oracle_audit_status": "PASS",
                            "oracle_audit_stale": False,
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                p.write_text(json.dumps({"schema_version": "1.0", "run_id": RUN_ID, "status": "PASS"}), encoding="utf-8")

    release_dir = tmp_path / "release"
    dest = finalize_release(
        run_id=RUN_ID,
        sources={name: run_dir / name for name in REQUIRED_RELEASE_FILES},
        release_root=release_dir,
    )
    assert dest.is_dir()


# =========================================================================
# A13: Wrong run_id in JSONL
# =========================================================================
def test_a13_wrong_run_id_in_jsonl(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    jsonl_file = run_dir / "telemetry.jsonl"
    jsonl_file.write_text(
        json.dumps({"run_id": "FOREIGN_RUN_ID", "event": "start"}) + "\n",
        encoding="utf-8",
    )
    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"
    assert len(report["mismatches"]) > 0


# =========================================================================
# A14: One wrong JSONL row among valid rows
# =========================================================================
def test_a14_one_wrong_jsonl_row_among_valid_rows(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    jsonl_file = run_dir / "telemetry.jsonl"
    lines = [json.dumps({"run_id": RUN_ID, "step": i}) for i in range(50)]
    lines[25] = json.dumps({"run_id": "ATTACKER_SNEAKY_RUN", "step": 25})
    jsonl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"
    assert any("ATTACKER_SNEAKY_RUN" in m["observed_run_id"] for m in report["mismatches"])


# =========================================================================
# A15: Missing mandatory gate definition
# =========================================================================
def test_a15_missing_mandatory_gate_definition() -> None:
    raw = {
        "schema_version": "1.0",
        "mandatory_gate_ids": ["B0", "B10", "B99_UNREGISTERED"],
        "gates": {
            "B0": {"gate_id": "B0", "hard": True, "requirements": {"m": {"operator": "eq", "value": True}}},
            "B10": {"gate_id": "B10", "hard": True, "requirements": {"m": {"operator": "eq", "value": True}}},
        },
        "methodology_note": "test",
    }
    with pytest.raises(Exception, match="GATE_REGISTRY_INCOMPLETE"):
        GateConfig.model_validate(raw)


# =========================================================================
# A16: Threshold change after freeze
# =========================================================================
def test_a16_threshold_change_after_freeze(tmp_path: Path) -> None:
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    # Attacker tampers with thresholds.txt after freeze
    thresh_file = tmp_path / "thresholds.txt"
    thresh_file.write_text("TAMPERED_THRESHOLD=0.1", encoding="utf-8")

    result = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas=shas,
    )
    assert result.status == FreezeStatus.INVALIDATED_CODE_CHANGE


# =========================================================================
# A17: Scoring before oracle audit
# =========================================================================
def test_a17_scoring_before_oracle_audit_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    freeze_path, checksum_path, shas = _valid_freeze(tmp_path, RUN_ID)
    tx.execute_freeze(freeze_path, checksum_path, repository_root=tmp_path, current_repository_shas=shas)

    # Skip oracle audit, attempt scoring
    with pytest.raises(TransactionError, match="Out-of-order"):
        tx.execute_scoring([])


# =========================================================================
# A18: Finalization before gate evaluation
# =========================================================================
def test_a18_finalization_before_gate_evaluation_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()

    with pytest.raises(TransactionError, match="Out-of-order"):
        tx.execute_release_finalization(tmp_path / "release")


# =========================================================================
# A19: Caller-forced lifecycle_valid=True
# =========================================================================
def test_a19_caller_forced_lifecycle_valid_rejected(tmp_path: Path) -> None:
    # Caller attempts to pass lifecycle_valid=True to evaluate_final_verdict while hard gates fail
    failing_gate = GateResult(
        gate_id="B10",
        hard=True,
        execution_status=ExecutionStatus.COMPLETED,
        status=GateStatus.FAIL,
        required={"m": {"operator": "gte", "value": 0.8}},
        observed={"m": 0.5},
        reason="failed",
        evidence=["retrieval.json"],
    )
    freeze_verif = verify_contract_freeze(
        *(_valid_freeze(tmp_path, RUN_ID)[:2]),
        repository_root=tmp_path,
        current_repository_shas=_valid_freeze(tmp_path, RUN_ID)[2],
    )
    verdict = evaluate_final_verdict(
        run_id=RUN_ID,
        gates=[failing_gate],
        mandatory_gate_ids={"B10"},
        mandatory_artifacts={"contract-freeze.json": True},
        freeze_verification=freeze_verif,
        lifecycle_valid=True,  # Attacker forces True!
    )
    assert verdict.status == VerdictStatus.PROFILE_B_FAIL
    assert verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE


# =========================================================================
# A20: Caller-forced final_verdict=PASS
# =========================================================================
def test_a20_caller_forced_final_verdict_rejected(tmp_path: Path) -> None:
    from harness.finalizer import REQUIRED_RELEASE_FILES

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in REQUIRED_RELEASE_FILES:
        p = source_dir / name
        if name == "final-report.md":
            p.write_text(f"# Report\n\nRun: {RUN_ID}\nStatus: PASS\n", encoding="utf-8")
        elif name == "gate-results.json":
            # Attacker forces top-level PASS claim
            p.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "run_id": RUN_ID,
                        "status": "PASS",
                        "final_verdict": "PROFILE_B_PASS_NATIVE",
                        # But omits mandatory gates or includes failed gates
                        "gates": [],
                    }
                ),
                encoding="utf-8",
            )
        else:
            p.write_text(json.dumps({"schema_version": "1.0", "run_id": RUN_ID, "status": "PASS"}), encoding="utf-8")

    with pytest.raises(ReleaseFinalizationError, match="gate-results.json has no gate results|tampered final_verdict|mandatory"):
        finalize_release(
            run_id=RUN_ID,
            sources={name: source_dir / name for name in REQUIRED_RELEASE_FILES},
            release_root=tmp_path / "release",
        )
