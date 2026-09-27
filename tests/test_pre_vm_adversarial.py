"""Independent false-PASS attacks added during the pre-VM completion audit."""

from __future__ import annotations

import json

import pytest

from harness.finalizer import ReleaseFinalizationError, finalize_release
from harness.metric_producers import (
    ProducerContext,
    ProducerIntegrityError,
    _b9,
    _b10,
    _b11,
    write_sealed_measurement,
)
from harness.scope_collector import (
    MESAContractIntegrityError,
    ScopeTestCase,
    collect_phase7_scope_isolation,
)
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


def _adversarial_ctx(tmp_path, run_id: str = "RUN-ADV", mesa_sha: str = "a" * 40) -> ProducerContext:
    from pathlib import Path
    from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
    freeze_dir = tmp_path / "freeze"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    materials = {}
    for cat in sorted(MANDATORY_MATERIAL_CATEGORIES):
        p = freeze_dir / f"{cat}.txt"
        p.write_text(cat, encoding="utf-8")
        materials[cat] = [p]
    repository_shas = {
        "MESA": mesa_sha,
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
    )
    return ProducerContext(
        run_dir=tmp_path,
        run_id=run_id,
        freeze_path=freeze_path,
        checksum_path=checksum_path,
        repository_root=tmp_path,
        current_repository_shas=repository_shas,
        raw_manifest_hash="m" * 64,
        gate_config_path=Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json",
    )


def _make_valid_scope_artifact(path, run_id: str, mesa_sha: str = "a" * 40) -> None:
    cases = [
        {
            "case_id": cid,
            "returned_forbidden_evidence_ids": [],
            "pre_rank_audit_verified": True,
            "exclusion_audit_hash": f"sha256:{'0'*64}",
            "evaluated_candidate_count": 10,
            "excluded_candidate_count": 5,
            "eligible_candidate_count": 5,
            "raw_response_sha256": "0" * 64,
        }
        for cid in [
            "cross_tenant_search",
            "cross_dataset_search",
            "cross_agent_search",
            "inactive_status_search",
            "wrong_jurisdiction_search",
            "stale_version_search",
            "effective_date_boundary_search",
            "context_visibility",
            "catalog_visibility",
            "document_visibility",
            "revision_visibility",
            "chunk_visibility",
        ]
    ]
    payload = {
        "schema_version": "2.0",
        "run_id": run_id,
        "contract_version": "mesa.scope-audit.v1",
        "mesa_sha": mesa_sha,
        "producer": "harness.scope_collector.collect_phase7_scope_isolation",
        "mesa_contract_capabilities": {
            "candidate_scope_identity": True,
            "pre_rank_exclusion_audit": True,
        },
        "negative_cases": cases,
    }
    write_sealed_measurement(path, payload)


def _make_valid_graph_artifact(path, run_id: str, mesa_sha: str = "a" * 40) -> None:
    pairs = [
        {
            "query_id": f"q-{i}",
            "dataset_id": "dataset-1",
            "pair_identity": f"pair-{i}",
            "scope_identity": {"tenant_id": "t1", "agent_id": "a1"},
            "on": {
                "query_id": f"q-{i}",
                "dataset_id": "dataset-1",
                "mesa_sha": mesa_sha,
                "settings_sha256": "s" * 64,
                "graph_enabled": True,
                "graph_backend_status": "OPERATIONAL",
                "complete_evidence_at_5": 1.0,
                "first_relevant_rank": 1,
                "top5_origins": [["graph"]],
                "paths": [{"graph_path_id": f"path-{i}", "path_valid": True}],
                "raw_response_sha256": "0" * 64,
                "pair_identity": f"pair-{i}",
                "contract_version": "mesa.graph-ablation.v1",
                "retrieval_config_identity": "cfg-1",
            },
            "off": {
                "query_id": f"q-{i}",
                "dataset_id": "dataset-1",
                "mesa_sha": mesa_sha,
                "settings_sha256": "s" * 64,
                "graph_enabled": False,
                "graph_backend_status": "DISABLED_BY_NATIVE_SWITCH",
                "complete_evidence_at_5": 0.5,
                "first_relevant_rank": 2,
                "top5_origins": [["vector"]],
                "paths": [],
                "raw_response_sha256": "0" * 64,
                "pair_identity": f"pair-{i}",
                "contract_version": "mesa.graph-ablation.v1",
                "retrieval_config_identity": "cfg-1",
            },
            "outcome": "positive",
        }
        for i in range(10)
    ]
    payload = {
        "schema_version": "2.0",
        "run_id": run_id,
        "contract_version": "mesa.graph-ablation.v1",
        "mesa_sha": mesa_sha,
        "producer": "harness.graph_collector.execute_paired_graph_ablation",
        "mesa_contract_capabilities": {
            "stable_path_identity": True,
            "native_graph_on_off_switch": True,
        },
        "graph_capability_operational": True,
        "frozen_state_proof": {
            "state_proof_contract_version": "mesa.state-proof.v1",
            "pre_composite_fingerprint": "sha256:" + "0" * 64,
            "post_composite_fingerprint": "sha256:" + "0" * 64,
            "sqlite_fingerprint": "sha256:" + "0" * 64,
            "lancedb_fingerprint": "sha256:" + "0" * 64,
            "kuzu_fingerprint": "sha256:" + "0" * 64,
            "quiescence_verified": True,
        },
        "pairs": pairs,
    }
    write_sealed_measurement(path, payload)


def test_adversarial_phase7_cross_run_stale_artifact_rejected(tmp_path) -> None:
    p = tmp_path / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-STALE-OLD")
    ctx = _adversarial_ctx(tmp_path, run_id="RUN-CURRENT-NEW")
    with pytest.raises(ProducerIntegrityError, match="RUN_ID mismatch"):
        _b9(ctx)


def test_adversarial_phase7_mesa_sha_mismatch_rejected(tmp_path) -> None:
    p = tmp_path / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV", mesa_sha="b" * 40)
    ctx = _adversarial_ctx(tmp_path, run_id="RUN-ADV", mesa_sha="a" * 40)
    with pytest.raises(ProducerIntegrityError, match="mesa_sha mismatch"):
        _b9(ctx)


def test_adversarial_phase7_principal_mismatch_rejected(tmp_path) -> None:
    from harness.scope_collector import build_canonical_scope_test_matrix
    from tests.test_phase7_scope_collector import _mock_mesa_response

    cases = build_canonical_scope_test_matrix()

    def evil_executor(case):
        resp = _mock_mesa_response(case)
        if "scope_audit" in resp:
            resp["scope_audit"]["requested_scope"]["principal_id"] = "principal-forged-evil"
        return resp

    with pytest.raises(MESAContractIntegrityError, match="principal mismatch"):
        collect_phase7_scope_isolation(
            run_id="RUN-ADV",
            run_dir=tmp_path,
            mesa_sha="a" * 40,
            test_cases=cases,
            mesa_executor=evil_executor,
        )


def test_adversarial_b11_cross_run_stale_artifact_rejected(tmp_path) -> None:
    p = tmp_path / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-STALE-OLD")
    ctx = _adversarial_ctx(tmp_path, run_id="RUN-CURRENT-NEW")
    with pytest.raises(ProducerIntegrityError, match="RUN_ID mismatch"):
        _b11(ctx)


def test_adversarial_b11_mesa_sha_mismatch_rejected(tmp_path) -> None:
    p = tmp_path / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV", mesa_sha="b" * 40)
    ctx = _adversarial_ctx(tmp_path, run_id="RUN-ADV", mesa_sha="a" * 40)
    with pytest.raises(ProducerIntegrityError, match="mesa_sha mismatch"):
        _b11(ctx)


def test_adversarial_b11_off_leaking_graph_paths_rejected(tmp_path) -> None:
    p = tmp_path / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["pairs"][0]["off"]["paths"] = [{"graph_path_id": "leak", "path_valid": True}]
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(tmp_path, run_id="RUN-ADV")
    with pytest.raises(ProducerIntegrityError, match="OFF pair leaked graph paths"):
        _b11(ctx)


def test_adversarial_b11_off_leaking_graph_origins_rejected(tmp_path) -> None:
    p = tmp_path / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["pairs"][0]["off"]["top5_origins"] = [["graph"]]
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(tmp_path, run_id="RUN-ADV")
    with pytest.raises(ProducerIntegrityError, match="OFF pair leaked graph origins in top-5"):
        _b11(ctx)


def test_adversarial_b11_mutated_store_during_execution_blocks_b11(tmp_path) -> None:
    p = tmp_path / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")
    payload = json.loads(p.read_text(encoding="utf-8"))
    # Mutate composite fingerprint between pre and post
    payload["frozen_state_proof"]["post_composite_fingerprint"] = "sha256:" + "f" * 64
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(tmp_path, run_id="RUN-ADV")
    obs = _b11(ctx)
    assert obs.execution == "BLOCKED"
    assert obs.reason.startswith("BLOCKED_BY_RUNTIME_STATE_PROOF:")
    assert "composite store fingerprint mutated" in obs.reason


def test_adversarial_b11_pair_identity_mismatch_rejected(tmp_path) -> None:
    p = tmp_path / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["pairs"][0]["off"]["pair_identity"] = "mismatched-pair-identity"
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(tmp_path, run_id="RUN-ADV")
    with pytest.raises(ProducerIntegrityError, match="unmatched graph ON/OFF pair"):
        _b11(ctx)

