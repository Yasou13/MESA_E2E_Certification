"""Fail-closed final Profile B verdict evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from harness.freeze import FreezeStatus, FreezeVerification
from harness.models import FinalVerdict, GateResult, GateStatus, VerdictStatus


def _verdict(
    run_id: str,
    status: VerdictStatus,
    reasons: list[str],
    gates: list[GateResult],
    missing_artifacts: list[str] | None = None,
) -> FinalVerdict:
    return FinalVerdict(
        run_id=run_id,
        status=status,
        reasons=reasons,
        gate_statuses={gate.gate_id: gate.status for gate in gates},
        missing_artifacts=missing_artifacts or [],
    )


def evaluate_final_verdict(
    *,
    run_id: str,
    gates: Iterable[GateResult],
    mandatory_gate_ids: set[str],
    mandatory_artifacts: dict[str, bool],
    freeze_verification: FreezeVerification,
    lifecycle_valid: bool,
) -> FinalVerdict:
    gate_list = list(gates)
    gate_ids = [gate.gate_id for gate in gate_list]
    if len(gate_ids) != len(set(gate_ids)):
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
            ["duplicate gate results"],
            gate_list,
        )

    if freeze_verification.status is FreezeStatus.INVALIDATED_CODE_CHANGE:
        return _verdict(
            run_id,
            VerdictStatus.INVALIDATED_CODE_CHANGE,
            freeze_verification.drift or ["frozen material drift"],
            gate_list,
        )
    if freeze_verification.status is not FreezeStatus.PASS:
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
            [f"freeze verification: {freeze_verification.status.value}"],
            gate_list,
        )
    if not lifecycle_valid:
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
            ["invalid run lifecycle"],
            gate_list,
        )

    missing_artifacts = sorted(
        name for name, present in mandatory_artifacts.items() if not present
    )
    if missing_artifacts:
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
            ["mandatory evidence is missing"],
            gate_list,
            missing_artifacts,
        )

    missing_gates = sorted(mandatory_gate_ids - set(gate_ids))
    if missing_gates:
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
            [f"mandatory gate results missing: {missing_gates}"],
            gate_list,
        )

    failed_hard = sorted(
        gate.gate_id
        for gate in gate_list
        if gate.hard and gate.status is GateStatus.FAIL
    )
    if failed_hard:
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_FAIL,
            [f"hard gates failed: {failed_hard}"],
            gate_list,
        )

    unverified_hard = sorted(
        gate.gate_id
        for gate in gate_list
        if gate.hard and gate.status is not GateStatus.PASS
    )
    if unverified_hard:
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
            [f"hard gates are not verified PASS: {unverified_hard}"],
            gate_list,
        )

    mandatory_by_id = {gate.gate_id: gate for gate in gate_list}
    mandatory_not_passed = sorted(
        gate_id
        for gate_id in mandatory_gate_ids
        if mandatory_by_id[gate_id].status is not GateStatus.PASS
    )
    if mandatory_not_passed:
        return _verdict(
            run_id,
            VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
            [f"mandatory gates are not PASS: {mandatory_not_passed}"],
            gate_list,
        )

    return _verdict(
        run_id,
        VerdictStatus.PROFILE_B_PASS_NATIVE,
        ["all mandatory artifacts, freeze checks, and hard gates passed"],
        gate_list,
    )


def write_final_verdict(verdict: FinalVerdict, path: str | Path) -> None:
    serialized = json.dumps(
        verdict.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    Path(path).write_text(serialized, encoding="utf-8", newline="\n")


def derive_production_verdict(
    *,
    run_id: str,
    gates: Iterable[GateResult],
    mandatory_gate_ids: set[str],
    run_dir: str | Path,
    freeze_path: str | Path,
    checksum_path: str | Path,
    repository_root: str | Path,
    current_repository_shas: dict[str, str],
    mandatory_artifact_names: Iterable[str],
) -> FinalVerdict:
    """Production entrypoint that recomputes trust directly from filesystem artifacts."""
    from harness.freeze import verify_contract_freeze
    from harness.gates import PROFILE_B_GATE_IDS, PRODUCTION_METRIC_PRODUCERS

    gate_list = list(gates)
    if mandatory_gate_ids != PROFILE_B_GATE_IDS or {g.gate_id for g in gate_list} != PROFILE_B_GATE_IDS:
        return _verdict(run_id, VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
                        ["mandatory production gate registry must be exactly B0-B14"], gate_list)

    run_path = Path(run_dir)
    freeze_verif = verify_contract_freeze(
        freeze_path=freeze_path,
        checksum_path=checksum_path,
        repository_root=repository_root,
        current_repository_shas=current_repository_shas,
    )

    manifest_path = run_path / "run_manifest.json"
    lifecycle_valid = False
    if manifest_path.is_file():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            if m.get("status") in {"PASS_NATIVE", "FINALIZING", "COMPLETED"}:
                lifecycle_valid = True
            if m.get("lifecycle_valid") is False:
                lifecycle_valid = False
            if m.get("lifecycle_status") in {"FAIL", "INVALIDATED", "BLOCKED", "INVALID"}:
                lifecycle_valid = False
        except Exception:
            lifecycle_valid = False

    mandatory_artifacts = {
        name: (run_path / name).is_file() for name in mandatory_artifact_names
    }

    verdict = evaluate_final_verdict(
        run_id=run_id,
        gates=gate_list,
        mandatory_gate_ids=mandatory_gate_ids,
        mandatory_artifacts=mandatory_artifacts,
        freeze_verification=freeze_verif,
        lifecycle_valid=lifecycle_valid,
    )
    if verdict.status == VerdictStatus.PROFILE_B_PASS_NATIVE and PROFILE_B_GATE_IDS - PRODUCTION_METRIC_PRODUCERS:
        return _verdict(run_id, VerdictStatus.PROFILE_B_BLOCKED_PRECONDITION,
                        ["authoritative metric producers unavailable; caller gate claims cannot certify"], gate_list)
    return verdict
