import hashlib
import json
from pathlib import Path

from harness.evidence import validate_run_id_consistency
from harness.gates import evaluate_threshold_gate, load_gate_config
from harness.models import ExecutionStatus, GateStatus


REPOSITORY = Path(__file__).resolve().parents[1]
RUN_ID = "RUN-20260901T005200Z-p8b03"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def test_historical_run_bytes_match_external_audit_manifest() -> None:
    manifest = (
        REPOSITORY / "reports" / "legacy-audits" / RUN_ID / "SHA256SUMS.txt"
    )
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        expected, relative = line.split("  ", 1)
        assert _sha256(REPOSITORY / relative) == expected


def test_historical_run_id_drift_is_recorded_without_mutation() -> None:
    report = validate_run_id_consistency(REPOSITORY / "runs" / RUN_ID, RUN_ID)
    invalidation = json.loads(
        (
            REPOSITORY
            / "reports"
            / "legacy-audits"
            / RUN_ID
            / "invalidation.json"
        ).read_text(encoding="utf-8")
    )

    assert report["status"] == "RUN_ID_MISMATCH"
    assert len(report["mismatches"]) == 9
    assert invalidation["original_evidence_mutated"] is False
    assert (
        invalidation["current_interpretation"]
        == "NOT_A_VALID_PROFILE_B_V2_CERTIFICATION_RESULT"
    )


def test_historical_pass_contradicts_executable_hard_thresholds() -> None:
    run_dir = REPOSITORY / "runs" / RUN_ID
    retrieval = json.loads(
        (run_dir / "retrieval-test-report.json").read_text(encoding="utf-8")
    )
    answers = json.loads(
        (run_dir / "answer-test-report.json").read_text(encoding="utf-8")
    )
    historical_verdict = json.loads(
        (run_dir / "verdict.json").read_text(encoding="utf-8")
    )
    config = load_gate_config(REPOSITORY / "config" / "profile-b-gates.json")
    scores = retrieval["query_scores"]
    single = [
        item
        for item in scores
        if item["query_class"] in {"SINGLE_DIRECT", "SINGLE_PARAPHRASE"}
    ]
    relational = [item for item in scores if item["query_class"] == "RELATIONAL"]
    b10 = evaluate_threshold_gate(
        config.gates["B10"],
        {
            "answerable_recall_at_5": retrieval["summary"]["overall_recall_at_5"],
            "single_hop_recall_at_5": sum(item["recall_at_5"] for item in single)
            / len(single),
            "answerable_mrr": retrieval["summary"]["overall_mrr_at_5"],
            "rel_complete_evidence_at_5": sum(
                item["complete_evidence_at_5"] for item in relational
            )
            / len(relational),
            "tenant_leakage": 0,
        },
        ExecutionStatus.COMPLETED,
        ["retrieval-test-report.json"],
    )
    b12 = evaluate_threshold_gate(
        config.gates["B12"],
        {
            "answerable_pass_rate": answers["summary"]["answerable_pass_rate"],
            "no_answer_pass_rate": answers["summary"]["no_answer_pass_rate"],
            "unsupported_material_claim_rate": 0,
            "fabricated_evidence_chunk_ids": 0,
        },
        ExecutionStatus.COMPLETED,
        ["answer-test-report.json"],
    )

    assert b10.status is GateStatus.FAIL
    assert b12.status is GateStatus.FAIL
    assert historical_verdict["certification_verdict"] == "PASS"
