from __future__ import annotations

from pathlib import Path

import pytest

from harness.freeze import FreezeStatus, FreezeVerification
from harness.gates import evaluate_threshold_gate, load_gate_config
from harness.models import ExecutionStatus, GateResult, GateStatus, VerdictStatus
from harness.verdict import evaluate_final_verdict


REPOSITORY = Path(__file__).resolve().parents[1]


def _gate(
    gate_id: str,
    status: GateStatus,
    *,
    hard: bool = True,
) -> GateResult:
    return GateResult(
        gate_id=gate_id,
        hard=hard,
        execution_status=ExecutionStatus.COMPLETED,
        status=status,
        required={},
        observed={},
        reason="test",
        evidence=["evidence.json"],
    )


@pytest.mark.parametrize(
    ("metric", "observed"),
    [
        ("answerable_recall_at_5", 0.79),
        ("single_hop_recall_at_5", 0.89),
        ("answerable_mrr", 0.69),
        ("rel_complete_evidence_at_5", 0.69),
    ],
)
def test_each_retrieval_threshold_failure_blocks_final_pass(
    metric: str, observed: float
) -> None:
    config = load_gate_config(REPOSITORY / "config" / "profile-b-gates.json")
    b10 = config.gates["B10"]
    values = {
        "answerable_recall_at_5": 1.0,
        "single_hop_recall_at_5": 1.0,
        "answerable_mrr": 1.0,
        "rel_complete_evidence_at_5": 1.0,
        "tenant_leakage": 0,
    }
    values[metric] = observed
    gate = evaluate_threshold_gate(
        b10, values, ExecutionStatus.COMPLETED, ["retrieval-summary.json"]
    )

    verdict = evaluate_final_verdict(
        run_id="RUN-test",
        gates=[gate],
        mandatory_gate_ids={"B10"},
        mandatory_artifacts={"contract-freeze.json": True},
        freeze_verification=FreezeVerification(FreezeStatus.PASS),
        lifecycle_valid=True,
    )

    assert gate.status is GateStatus.FAIL
    assert verdict.status is VerdictStatus.PROFILE_B_FAIL


def test_execution_success_is_distinct_from_gate_failure() -> None:
    config = load_gate_config(REPOSITORY / "config" / "profile-b-gates.json")
    gate = evaluate_threshold_gate(
        config.gates["B10"],
        {
            "answerable_recall_at_5": 0.7,
            "single_hop_recall_at_5": 0.7,
            "answerable_mrr": 0.5,
            "rel_complete_evidence_at_5": 0.5,
            "tenant_leakage": 0,
        },
        ExecutionStatus.COMPLETED,
        ["retrieval-summary.json"],
    )

    assert gate.execution_status is ExecutionStatus.COMPLETED
    assert gate.status is GateStatus.FAIL


def test_answer_gate_failure_blocks_pass_while_current_contract_is_hard() -> None:
    config = load_gate_config(REPOSITORY / "config" / "profile-b-gates.json")
    gate = evaluate_threshold_gate(
        config.gates["B12"],
        {
            "answerable_pass_rate": 0.79,
            "no_answer_pass_rate": 1.0,
            "unsupported_material_claim_rate": 0,
            "fabricated_evidence_chunk_ids": 0,
        },
        ExecutionStatus.COMPLETED,
        ["answer-summary.json"],
    )
    verdict = evaluate_final_verdict(
        run_id="RUN-test",
        gates=[gate],
        mandatory_gate_ids={"B12"},
        mandatory_artifacts={"contract-freeze.json": True},
        freeze_verification=FreezeVerification(FreezeStatus.PASS),
        lifecycle_valid=True,
    )

    assert gate.hard is True
    assert verdict.status is VerdictStatus.PROFILE_B_FAIL


@pytest.mark.parametrize(
    ("freeze_status", "expected"),
    [
        (FreezeStatus.MISSING_FREEZE, VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION),
        (FreezeStatus.INVALID_FREEZE, VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION),
        (FreezeStatus.INVALIDATED_CODE_CHANGE, VerdictStatus.INVALIDATED_CODE_CHANGE),
    ],
)
def test_missing_or_drifted_freeze_can_never_pass(
    freeze_status: FreezeStatus, expected: VerdictStatus
) -> None:
    verdict = evaluate_final_verdict(
        run_id="RUN-test",
        gates=[_gate("B10", GateStatus.PASS)],
        mandatory_gate_ids={"B10"},
        mandatory_artifacts={"contract-freeze.json": True},
        freeze_verification=FreezeVerification(freeze_status, ["freeze failure"]),
        lifecycle_valid=True,
    )
    assert verdict.status is expected


def test_missing_artifact_unverified_gate_or_invalid_lifecycle_cannot_pass() -> None:
    common = dict(
        run_id="RUN-test",
        mandatory_gate_ids={"B10"},
        freeze_verification=FreezeVerification(FreezeStatus.PASS),
    )
    missing = evaluate_final_verdict(
        **common,
        gates=[_gate("B10", GateStatus.PASS)],
        mandatory_artifacts={"health-post-test.json": False},
        lifecycle_valid=True,
    )
    unverified = evaluate_final_verdict(
        **common,
        gates=[_gate("B10", GateStatus.UNVERIFIED)],
        mandatory_artifacts={"health-post-test.json": True},
        lifecycle_valid=True,
    )
    lifecycle = evaluate_final_verdict(
        **common,
        gates=[_gate("B10", GateStatus.PASS)],
        mandatory_artifacts={"health-post-test.json": True},
        lifecycle_valid=False,
    )

    assert missing.status is not VerdictStatus.PROFILE_B_PASS_NATIVE
    assert unverified.status is not VerdictStatus.PROFILE_B_PASS_NATIVE
    assert lifecycle.status is not VerdictStatus.PROFILE_B_PASS_NATIVE


def test_only_complete_hard_pass_set_can_pass_native() -> None:
    verdict = evaluate_final_verdict(
        run_id="RUN-test",
        gates=[
            _gate("B10", GateStatus.PASS),
            _gate("diagnostic", GateStatus.FAIL, hard=False),
        ],
        mandatory_gate_ids={"B10"},
        mandatory_artifacts={
            "contract-freeze.json": True,
            "health-post-test.json": True,
        },
        freeze_verification=FreezeVerification(FreezeStatus.PASS),
        lifecycle_valid=True,
    )

    assert verdict.status is VerdictStatus.PROFILE_B_PASS_NATIVE
