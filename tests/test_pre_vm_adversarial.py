"""Independent false-PASS attacks added during the pre-VM completion audit."""

from __future__ import annotations

import json

import pytest

from harness.finalizer import ReleaseFinalizationError, finalize_release
from tests.independent_support import placeholder_sources


def test_all_b0_b14_status_only_pass_rows_cannot_finalize(tmp_path) -> None:
    sources = placeholder_sources(tmp_path)
    gate_payload = json.loads(sources["gate-results.json"].read_text())
    gate_payload.update(
        {
            "final_verdict": "PROFILE_B_PASS_NATIVE",
            "mandatory_gate_ids": [f"B{index}" for index in range(15)],
            "gates": [
                {
                    "schema_version": "1.0",
                    "gate_id": f"B{index}",
                    "hard": True,
                    "execution_status": "COMPLETED",
                    "status": "PASS",
                    "required": {},
                    "observed": {},
                    "reason": "forged status-only pass",
                    "evidence": [],
                }
                for index in range(15)
            ],
        }
    )
    sources["gate-results.json"].write_text(json.dumps(gate_payload))

    with pytest.raises(
        ReleaseFinalizationError, match="requirements|authoritative evidence"
    ):
        finalize_release(
            run_id="RUN-independent",
            sources=sources,
            release_root=tmp_path / "release",
        )


def test_lowered_gate_threshold_rejected_by_finalizer(tmp_path) -> None:
    import hashlib
    from pathlib import Path
    from harness.gates import load_gate_config

    sources = placeholder_sources(tmp_path)
    gate_payload = json.loads(sources["gate-results.json"].read_text())
    config = load_gate_config(
        Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json"
    )
    valid_evidence = (
        "answer-summary.json#sha256="
        + hashlib.sha256(sources["answer-summary.json"].read_bytes()).hexdigest()
    )
    gates = []
    for gid in sorted(config.mandatory_gate_ids):
        req = {
            k: v.model_dump(mode="json")
            for k, v in config.gates[gid].requirements.items()
        }
        if gid == "B10":
            # Attacker tampers with the recall threshold to lower it
            req["single_hop_recall_at_5"] = {"operator": "gte", "value": 0.01}
        gates.append(
            {
                "schema_version": "1.0",
                "gate_id": gid,
                "hard": True,
                "execution_status": "COMPLETED",
                "status": "PASS",
                "required": req,
                "observed": {k: 1.0 for k in req},
                "reason": "thresholds_met",
                "evidence": [valid_evidence],
            }
        )
    gate_payload.update(
        {
            "final_verdict": "PROFILE_B_PASS_NATIVE",
            "mandatory_gate_ids": list(config.mandatory_gate_ids),
            "gates": gates,
        }
    )
    sources["gate-results.json"].write_text(json.dumps(gate_payload))

    with pytest.raises(
        ReleaseFinalizationError, match="requirements differ from authoritative config"
    ):
        finalize_release(
            run_id="RUN-independent",
            sources=sources,
            release_root=tmp_path / "release",
        )


def test_unindexed_or_hash_mismatched_gate_evidence_rejected(tmp_path) -> None:
    import hashlib
    from pathlib import Path
    from harness.gates import load_gate_config

    sources = placeholder_sources(tmp_path)
    gate_payload = json.loads(sources["gate-results.json"].read_text())
    config = load_gate_config(
        Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json"
    )
    gates = []
    for gid in sorted(config.mandatory_gate_ids):
        req = {
            k: v.model_dump(mode="json")
            for k, v in config.gates[gid].requirements.items()
        }
        # Tamper evidence reference hash for B10
        if gid == "B10":
            evidence_ref = "answer-summary.json#sha256=" + ("0" * 64)
        else:
            evidence_ref = (
                "answer-summary.json#sha256="
                + hashlib.sha256(
                    sources["answer-summary.json"].read_bytes()
                ).hexdigest()
            )
        gates.append(
            {
                "schema_version": "1.0",
                "gate_id": gid,
                "hard": True,
                "execution_status": "COMPLETED",
                "status": "PASS",
                "required": req,
                "observed": {k: 1.0 for k in req},
                "reason": "thresholds_met",
                "evidence": [evidence_ref],
            }
        )
    gate_payload.update(
        {
            "final_verdict": "PROFILE_B_PASS_NATIVE",
            "mandatory_gate_ids": list(config.mandatory_gate_ids),
            "gates": gates,
        }
    )
    sources["gate-results.json"].write_text(json.dumps(gate_payload))

    with pytest.raises(
        ReleaseFinalizationError,
        match="absent from the authoritative index or hash-mismatched",
    ):
        finalize_release(
            run_id="RUN-independent",
            sources=sources,
            release_root=tmp_path / "release",
        )


def test_hard_gate_blocked_cannot_claim_pass_final_verdict(tmp_path) -> None:
    import hashlib
    from pathlib import Path
    from harness.gates import load_gate_config

    sources = placeholder_sources(tmp_path)
    gate_payload = json.loads(sources["gate-results.json"].read_text())
    config = load_gate_config(
        Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json"
    )
    valid_evidence = (
        "answer-summary.json#sha256="
        + hashlib.sha256(sources["answer-summary.json"].read_bytes()).hexdigest()
    )
    gates = []
    for gid in sorted(config.mandatory_gate_ids):
        req = {
            k: v.model_dump(mode="json")
            for k, v in config.gates[gid].requirements.items()
        }
        status = "BLOCKED" if gid == "B9" else "PASS"
        exec_status = "BLOCKED" if gid == "B9" else "COMPLETED"
        gates.append(
            {
                "schema_version": "1.0",
                "gate_id": gid,
                "hard": True,
                "execution_status": exec_status,
                "status": status,
                "required": req,
                "observed": {k: 1.0 for k in req},
                "reason": (
                    "BLOCKED_BY_MESA_CONTRACT" if gid == "B9" else "thresholds_met"
                ),
                "evidence": [valid_evidence],
            }
        )
    gate_payload.update(
        {
            "final_verdict": "PROFILE_B_PASS_NATIVE",
            "mandatory_gate_ids": list(config.mandatory_gate_ids),
            "gates": gates,
        }
    )
    sources["gate-results.json"].write_text(json.dumps(gate_payload))

    with pytest.raises(
        ReleaseFinalizationError, match="hard gate B9 has status BLOCKED"
    ):
        finalize_release(
            run_id="RUN-independent",
            sources=sources,
            release_root=tmp_path / "release",
        )


def test_missing_mandatory_gate_in_registry_cannot_finalize(tmp_path) -> None:
    import hashlib
    from pathlib import Path
    from harness.gates import load_gate_config

    sources = placeholder_sources(tmp_path)
    gate_payload = json.loads(sources["gate-results.json"].read_text())
    config = load_gate_config(
        Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json"
    )
    valid_evidence = (
        "answer-summary.json#sha256="
        + hashlib.sha256(sources["answer-summary.json"].read_bytes()).hexdigest()
    )
    gates = []
    for gid in sorted(config.mandatory_gate_ids):
        if gid == "B14":
            continue  # Attacker maliciously omits mandatory gate B14
        req = {
            k: v.model_dump(mode="json")
            for k, v in config.gates[gid].requirements.items()
        }
        gates.append(
            {
                "schema_version": "1.0",
                "gate_id": gid,
                "hard": True,
                "execution_status": "COMPLETED",
                "status": "PASS",
                "required": req,
                "observed": {k: 1.0 for k in req},
                "reason": "thresholds_met",
                "evidence": [valid_evidence],
            }
        )
    gate_payload.update(
        {
            "final_verdict": "PROFILE_B_PASS_NATIVE",
            "mandatory_gate_ids": [
                gid for gid in config.mandatory_gate_ids if gid != "B14"
            ],
            "gates": gates,
        }
    )
    sources["gate-results.json"].write_text(json.dumps(gate_payload))

    with pytest.raises(
        ReleaseFinalizationError,
        match="mandatory gate registry must contain exactly B0-B14",
    ):
        finalize_release(
            run_id="RUN-independent",
            sources=sources,
            release_root=tmp_path / "release",
        )
