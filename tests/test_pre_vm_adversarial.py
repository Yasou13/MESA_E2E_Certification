"""Independent false-PASS attacks added during the pre-VM completion audit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.finalizer import ReleaseFinalizationError, finalize_release
from harness.metric_producers import (
    ProducerContext,
    ProducerIntegrityError,
    _b9,
    _b11,
    write_sealed_measurement,
)
from harness.scope_collector import (
    MESAContractIntegrityError,
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


def _adversarial_ctx(
    run_dir: Path, run_id: str = "RUN-ADV", mesa_sha: str = "a" * 40
) -> ProducerContext:
    from pathlib import Path
    from harness.artifacts import RunArtifactStore
    from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze

    freeze_dir = run_dir / "freeze"
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
    store = RunArtifactStore(run_dir, run_id=run_id)
    manifest_info = store.compute_raw_manifest()
    store._write_immutable_json(run_dir / "raw-manifest.json", manifest_info)
    raw_hash = manifest_info["manifest_hash"]

    return ProducerContext(
        run_dir=run_dir,
        run_id=run_id,
        freeze_path=freeze_path,
        checksum_path=checksum_path,
        repository_root=run_dir,
        current_repository_shas=repository_shas,
        raw_manifest_hash=raw_hash,
        gate_config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "profile-b-gates.json",
    )


def _make_valid_scope_artifact(
    path: Path, run_id: str, mesa_sha: str = "a" * 40
) -> None:
    import hashlib

    run_dir = path.parent
    raw_dir = run_dir / "raw" / "scope"
    raw_dir.mkdir(parents=True, exist_ok=True)
    search_ids = {
        "cross_tenant_search",
        "cross_dataset_search",
        "cross_agent_search",
        "inactive_status_search",
        "wrong_jurisdiction_search",
        "stale_version_search",
        "effective_date_boundary_search",
    }
    all_ids = [
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
    cases = []
    for cid in all_ids:
        raw_file = raw_dir / f"{cid}.json"
        raw_payload = {"schema_version": "1.0", "run_id": run_id, "case_id": cid}
        raw_bytes = (json.dumps(raw_payload, sort_keys=True) + "\n").encode("utf-8")
        raw_file.write_bytes(raw_bytes)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        raw_file.with_suffix(raw_file.suffix + ".SHA256").write_text(
            f"{raw_sha}  {raw_file.name}\n"
        )

        if cid in search_ids:
            case_entry = {
                "case_id": cid,
                "proof_type": "search_pre_rank_scope",
                "source_raw_artifact": f"raw/scope/{cid}.json",
                "source_raw_sha256": raw_sha,
                "raw_response_sha256": "0" * 64,
                "returned_forbidden_evidence_ids": [],
                "pre_rank_audit_verified": True,
                "exclusion_audit_hash": f"sha256:{'0'*64}",
                "evaluated_candidate_count": 10,
                "excluded_candidate_count": 5,
                "eligible_candidate_count": 5,
            }
        else:
            case_entry = {
                "case_id": cid,
                "proof_type": "endpoint_visibility",
                "source_raw_artifact": f"raw/scope/{cid}.json",
                "source_raw_sha256": raw_sha,
                "raw_response_sha256": "0" * 64,
                "returned_forbidden_evidence_ids": [],
                "endpoint_visibility_verified": True,
                "pre_rank_audit_verified": False,
                "exclusion_audit_hash": None,
                "evaluated_candidate_count": None,
                "excluded_candidate_count": None,
                "eligible_candidate_count": None,
            }
        cases.append(case_entry)

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


def _make_valid_graph_artifact(
    path: Path, run_id: str, mesa_sha: str = "a" * 40
) -> None:
    import hashlib

    run_dir = path.parent
    raw_graph_dir = run_dir / "raw" / "graph"
    raw_graph_dir.mkdir(parents=True, exist_ok=True)
    raw_state_dir = run_dir / "raw" / "state"
    raw_state_dir.mkdir(parents=True, exist_ok=True)

    state_file = raw_state_dir / "state-proof.json"
    state_payload = {
        "schema_version": "1.0",
        "run_id": run_id,
        "collector_version": "harness.state_proof.v2",
        "retrieval_state_unchanged": True,
        "proof_mode": "stable_state_pair",
        "pair_state_stability_verified": True,
        "runtime_quiescence_verified": False,
        "quiescence_verified": False,
        "state_stability_evidence": {
            "proof_mode": "stable_state_pair",
            "writer_lock_acquired_by_e2e": False,
            "pair_state_stability_verified": True,
            "runtime_quiescence_verified": False,
            "pre_writer_observation": {"pid": 123, "process_start_ticks": 456},
            "post_writer_observation": {"pid": 123, "process_start_ticks": 456},
            "pre_mutation_marker_sha256": "a" * 64,
            "post_mutation_marker_sha256": "a" * 64,
        },
        "pre_composite_fingerprint": "sha256:" + "0" * 64,
        "post_composite_fingerprint": "sha256:" + "0" * 64,
    }
    state_bytes = (json.dumps(state_payload, sort_keys=True) + "\n").encode("utf-8")
    state_file.write_bytes(state_bytes)
    state_sha = hashlib.sha256(state_bytes).hexdigest()
    state_file.with_suffix(state_file.suffix + ".SHA256").write_text(
        f"{state_sha}  {state_file.name}\n"
    )

    pairs = []
    for i in range(10):
        qid = f"q-{i}"
        on_file = raw_graph_dir / f"{qid}_on.json"
        on_payload = {
            "schema_version": "1.0",
            "run_id": run_id,
            "query_id": qid,
            "mode": "enabled",
            "graph_enabled": True,
        }
        on_bytes = (json.dumps(on_payload, sort_keys=True) + "\n").encode("utf-8")
        on_file.write_bytes(on_bytes)
        on_sha = hashlib.sha256(on_bytes).hexdigest()
        on_file.with_suffix(on_file.suffix + ".SHA256").write_text(
            f"{on_sha}  {on_file.name}\n"
        )

        off_file = raw_graph_dir / f"{qid}_off.json"
        off_payload = {
            "schema_version": "1.0",
            "run_id": run_id,
            "query_id": qid,
            "mode": "disabled",
            "graph_enabled": False,
        }
        off_bytes = (json.dumps(off_payload, sort_keys=True) + "\n").encode("utf-8")
        off_file.write_bytes(off_bytes)
        off_sha = hashlib.sha256(off_bytes).hexdigest()
        off_file.with_suffix(off_file.suffix + ".SHA256").write_text(
            f"{off_sha}  {off_file.name}\n"
        )

        pairs.append(
            {
                "query_id": qid,
                "dataset_id": "dataset-1",
                "pair_identity": f"pair-{i}",
                "scope_identity": {"tenant_id": "t1", "agent_id": "a1"},
                "on": {
                    "query_id": qid,
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
                    "on_raw_artifact": f"raw/graph/{qid}_on.json",
                    "on_raw_sha256": on_sha,
                    "pair_identity": f"pair-{i}",
                    "contract_version": "mesa.graph-ablation.v1",
                    "retrieval_config_identity": "cfg-1",
                },
                "off": {
                    "query_id": qid,
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
                    "off_raw_artifact": f"raw/graph/{qid}_off.json",
                    "off_raw_sha256": off_sha,
                    "pair_identity": f"pair-{i}",
                    "contract_version": "mesa.graph-ablation.v1",
                    "retrieval_config_identity": "cfg-1",
                },
                "outcome": "positive",
            }
        )

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
        "state_proof_artifact": "raw/state/state-proof.json",
        "state_proof_sha256": state_sha,
        "frozen_state_proof": {
            "state_proof_contract_version": "mesa.state-proof.v2",
            "pre_composite_fingerprint": "sha256:" + "0" * 64,
            "post_composite_fingerprint": "sha256:" + "0" * 64,
            "sqlite_fingerprint": "sha256:" + "0" * 64,
            "lancedb_fingerprint": "sha256:" + "0" * 64,
            "kuzu_fingerprint": "sha256:" + "0" * 64,
            "retrieval_state_unchanged": True,
            "proof_mode": "stable_state_pair",
            "pair_state_stability_verified": True,
            "runtime_quiescence_verified": False,
            "quiescence_verified": False,
        },
        "pairs": pairs,
    }
    write_sealed_measurement(path, payload)


# ---------------- BLOCKER 1 ATTACKS: FORGED ARTIFACT REJECTION ----------------


def test_adversarial_b9_forged_scope_artifact_without_raw_manifest_rejected(
    tmp_path,
) -> None:
    """Blocker 1: Valid JSON + valid sidecar without raw manifest fails closed."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    # Create payload with NO raw files or manifest
    cases = [
        {
            "case_id": cid,
            "proof_type": (
                "search_pre_rank_scope" if "search" in cid else "endpoint_visibility"
            ),
            "source_raw_artifact": f"raw/scope/{cid}.json",
            "source_raw_sha256": "0" * 64,
            "returned_forbidden_evidence_ids": [],
            "pre_rank_audit_verified": "search" in cid,
            "endpoint_visibility_verified": "search" not in cid,
            "exclusion_audit_hash": f"sha256:{'0'*64}" if "search" in cid else None,
            "evaluated_candidate_count": 10 if "search" in cid else None,
            "excluded_candidate_count": 5 if "search" in cid else None,
            "eligible_candidate_count": 5 if "search" in cid else None,
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
        "run_id": "RUN-ADV",
        "contract_version": "mesa.scope-audit.v1",
        "mesa_sha": "a" * 40,
        "producer": "harness.scope_collector.collect_phase7_scope_isolation",
        "mesa_contract_capabilities": {
            "candidate_scope_identity": True,
            "pre_rank_exclusion_audit": True,
        },
        "negative_cases": cases,
    }
    write_sealed_measurement(p, payload)

    # Context without raw-manifest
    freeze_dir = run_dir / "freeze"
    freeze_dir.mkdir()
    from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze

    materials = {
        cat: [freeze_dir / f"{cat}.txt"]
        for cat in sorted(MANDATORY_MATERIAL_CATEGORIES)
    }
    for cat in materials:
        materials[cat][0].write_text(cat)
    shas = {"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40}
    fp, cs = create_contract_freeze(
        output_dir=freeze_dir,
        run_id="RUN-ADV",
        repository_root=freeze_dir,
        repository_shas=shas,
        material_paths=materials,
        runtime_identities={"python": "3.13.12"},
    )
    ctx = ProducerContext(
        run_dir=run_dir,
        run_id="RUN-ADV",
        freeze_path=fp,
        checksum_path=cs,
        repository_root=run_dir,
        current_repository_shas=shas,
        raw_manifest_hash="m" * 64,
        gate_config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "profile-b-gates.json",
    )
    with pytest.raises(
        ProducerIntegrityError, match="missing sealed artifact: raw-manifest.json"
    ):
        _b9(ctx)


def test_adversarial_b11_forged_graph_artifact_without_raw_manifest_rejected(
    tmp_path,
) -> None:
    """Blocker 1: Valid JSON + valid sidecar without raw manifest fails closed."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    payload = {
        "schema_version": "2.0",
        "run_id": "RUN-ADV",
        "contract_version": "mesa.graph-ablation.v1",
        "mesa_sha": "a" * 40,
        "producer": "harness.graph_collector.execute_paired_graph_ablation",
        "mesa_contract_capabilities": {
            "stable_path_identity": True,
            "native_graph_on_off_switch": True,
        },
        "graph_capability_operational": True,
        "state_proof_artifact": "raw/state/state-proof.json",
        "state_proof_sha256": "0" * 64,
        "frozen_state_proof": {
            "state_proof_contract_version": "mesa.state-proof.v1",
            "pre_composite_fingerprint": "sha256:" + "0" * 64,
            "post_composite_fingerprint": "sha256:" + "0" * 64,
            "sqlite_fingerprint": "sha256:" + "0" * 64,
            "lancedb_fingerprint": "sha256:" + "0" * 64,
            "kuzu_fingerprint": "sha256:" + "0" * 64,
            "retrieval_state_unchanged": True,
            "quiescence_verified": True,
        },
        "pairs": [],
    }
    write_sealed_measurement(p, payload)

    freeze_dir = run_dir / "freeze"
    freeze_dir.mkdir()
    from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze

    materials = {
        cat: [freeze_dir / f"{cat}.txt"]
        for cat in sorted(MANDATORY_MATERIAL_CATEGORIES)
    }
    for cat in materials:
        materials[cat][0].write_text(cat)
    shas = {"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40}
    fp, cs = create_contract_freeze(
        output_dir=freeze_dir,
        run_id="RUN-ADV",
        repository_root=freeze_dir,
        repository_shas=shas,
        material_paths=materials,
        runtime_identities={"python": "3.13.12"},
    )
    ctx = ProducerContext(
        run_dir=run_dir,
        run_id="RUN-ADV",
        freeze_path=fp,
        checksum_path=cs,
        repository_root=run_dir,
        current_repository_shas=shas,
        raw_manifest_hash="m" * 64,
        gate_config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "profile-b-gates.json",
    )
    with pytest.raises(
        ProducerIntegrityError, match="missing sealed artifact: raw-manifest.json"
    ):
        _b11(ctx)


def test_adversarial_raw_lineage_valid_sha_not_in_raw_manifest_rejected(
    tmp_path,
) -> None:
    """Raw file exists and sidecar is valid, but raw-manifest does NOT list it."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")

    # Tamper with scope-isolation to reference an unmanifested raw file
    payload = json.loads(p.read_text(encoding="utf-8"))
    unindexed = run_dir / "raw" / "scope" / "unindexed.json"
    unindexed.write_text('{"run_id": "RUN-ADV", "case_id": "cross_tenant_search"}\n')
    import hashlib

    u_sha = hashlib.sha256(unindexed.read_bytes()).hexdigest()
    unindexed.with_suffix(".json.SHA256").write_text(f"{u_sha}  unindexed.json\n")

    payload["negative_cases"][0]["source_raw_artifact"] = "raw/scope/unindexed.json"
    payload["negative_cases"][0]["source_raw_sha256"] = u_sha
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(ProducerIntegrityError, match="absent from sealed raw manifest"):
        _b9(ctx)


def test_adversarial_raw_lineage_wrong_raw_hash_rejected(tmp_path) -> None:
    """Artifact references correct raw path but supplies forged hash."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["negative_cases"][0]["source_raw_sha256"] = "f" * 64
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(
        ProducerIntegrityError, match="does not match sealed raw manifest"
    ):
        _b9(ctx)


def test_adversarial_raw_lineage_stale_raw_from_other_run_rejected(tmp_path) -> None:
    """Raw artifact contains a different run_id than current context."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV")

    # Overwrite one raw file with wrong run_id
    raw_file = run_dir / "raw" / "scope" / "cross_tenant_search.json"
    raw_payload = {
        "schema_version": "1.0",
        "run_id": "RUN-STALE-PREVIOUS",
        "case_id": "cross_tenant_search",
    }
    raw_bytes = (json.dumps(raw_payload, sort_keys=True) + "\n").encode("utf-8")
    raw_file.write_bytes(raw_bytes)
    import hashlib

    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    raw_file.with_suffix(".json.SHA256").write_text(f"{raw_sha}  {raw_file.name}\n")

    from harness.artifacts import ArtifactStoreError, RunArtifactStore

    store = RunArtifactStore(run_dir, run_id="RUN-ADV")
    with pytest.raises(ArtifactStoreError, match="raw artifact run_id mismatch"):
        store.compute_raw_manifest()


# ---------------- BLOCKER 2 ATTACKS: SYNTHETIC AUDIT PROOF ----------------


def test_adversarial_phase7_non_search_synthetic_pre_rank_verified_rejected(
    tmp_path,
) -> None:
    """Blocker 2: Non-search case claiming pre_rank_audit_verified=True is rejected."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")

    payload = json.loads(p.read_text(encoding="utf-8"))
    # Find a non-search case (e.g. context_visibility) and inject pre_rank_audit_verified=True
    for c in payload["negative_cases"]:
        if c["case_id"] == "context_visibility":
            c["pre_rank_audit_verified"] = True
            break
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(
        ProducerIntegrityError, match="cannot claim pre_rank_audit_verified"
    ):
        _b9(ctx)


def test_adversarial_phase7_non_search_synthetic_audit_counts_rejected(
    tmp_path,
) -> None:
    """Blocker 2: Non-search case synthesizing candidate counts is rejected."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")

    payload = json.loads(p.read_text(encoding="utf-8"))
    for c in payload["negative_cases"]:
        if c["case_id"] == "context_visibility":
            c["evaluated_candidate_count"] = 10
            c["excluded_candidate_count"] = 5
            c["eligible_candidate_count"] = 5
            break
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(
        ProducerIntegrityError, match="cannot synthesize candidate counts"
    ):
        _b9(ctx)


def test_adversarial_phase7_non_search_synthetic_exclusion_hash_rejected(
    tmp_path,
) -> None:
    """Blocker 2: Non-search case synthesizing exclusion_audit_hash is rejected."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")

    payload = json.loads(p.read_text(encoding="utf-8"))
    for c in payload["negative_cases"]:
        if c["case_id"] == "document_visibility":
            c["exclusion_audit_hash"] = f"sha256:{'0'*64}"
            break
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(
        ProducerIntegrityError, match="cannot synthesize exclusion_audit_hash"
    ):
        _b9(ctx)


def test_adversarial_phase7_endpoint_visibility_proof_passed_as_search_proof_rejected(
    tmp_path,
) -> None:
    """Search case pretending to be endpoint_visibility is rejected."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")

    payload = json.loads(p.read_text(encoding="utf-8"))
    for c in payload["negative_cases"]:
        if c["case_id"] == "cross_tenant_search":
            c["proof_type"] = "endpoint_visibility"
            break
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(
        ProducerIntegrityError, match="must have proof_type='search_pre_rank_scope'"
    ):
        _b9(ctx)


# ---------------- GAP 3 ATTACKS: QUIESCENCE / STATE PROOF ----------------


def test_adversarial_b11_forged_quiescence_boolean_rejected(tmp_path) -> None:
    """A graph artifact cannot upgrade stable-state evidence into quiescence."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")

    # The sealed proof honestly says no native runtime freeze was verified.
    state_file = run_dir / "raw" / "state" / "state-proof.json"
    s_payload = json.loads(state_file.read_text(encoding="utf-8"))
    s_payload["quiescence_verified"] = False
    s_bytes = (json.dumps(s_payload, sort_keys=True) + "\n").encode("utf-8")
    state_file.write_bytes(s_bytes)
    import hashlib

    s_sha = hashlib.sha256(s_bytes).hexdigest()
    state_file.with_suffix(".json.SHA256").write_text(f"{s_sha}  {state_file.name}\n")

    # Update graph-ablation.json state_proof_sha256 but KEEP quiescence_verified=True
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["state_proof_sha256"] = s_sha
    payload["frozen_state_proof"]["quiescence_verified"] = True
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")
    with pytest.raises(
        ProducerIntegrityError,
        match="falsely claims runtime quiescence",
    ):
        _b11(ctx)


def test_adversarial_b11_unstable_pair_blocks_b11(tmp_path) -> None:
    """B11 fails closed when paired state stability is not verified."""
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")

    state_file = run_dir / "raw" / "state" / "state-proof.json"
    s_payload = json.loads(state_file.read_text(encoding="utf-8"))
    s_payload["proof_mode"] = "unverified"
    s_payload["pair_state_stability_verified"] = False
    s_payload["state_stability_evidence"] = {}
    s_bytes = (json.dumps(s_payload, sort_keys=True) + "\n").encode("utf-8")
    state_file.write_bytes(s_bytes)
    import hashlib

    s_sha = hashlib.sha256(s_bytes).hexdigest()
    state_file.with_suffix(".json.SHA256").write_text(f"{s_sha}  {state_file.name}\n")

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["state_proof_sha256"] = s_sha
    payload["frozen_state_proof"]["proof_mode"] = "unverified"
    payload["frozen_state_proof"]["pair_state_stability_verified"] = False
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")
    obs = _b11(ctx)
    assert obs.execution == "BLOCKED"
    assert "BLOCKED_BY_RUNTIME_STATE_PROOF" in obs.reason


# ---------------- EXISTING ADVERSARIAL TESTS PRESERVED ----------------


def test_adversarial_phase7_cross_run_stale_artifact_rejected(tmp_path) -> None:
    run_dir = tmp_path / "RUN-CURRENT-NEW"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-CURRENT-NEW")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-CURRENT-NEW")

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["run_id"] = "RUN-STALE-OLD"
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(ProducerIntegrityError, match="(?i)run_id mismatch"):
        _b9(ctx)


def test_adversarial_phase7_mesa_sha_mismatch_rejected(tmp_path) -> None:
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "scope-isolation.json"
    _make_valid_scope_artifact(p, run_id="RUN-ADV", mesa_sha="b" * 40)
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV", mesa_sha="a" * 40)
    with pytest.raises(ProducerIntegrityError, match="mesa_sha mismatch"):
        _b9(ctx)


def test_adversarial_phase7_principal_mismatch_rejected(tmp_path) -> None:
    from harness.scope_collector import build_canonical_scope_test_matrix
    from tests.test_phase7_scope_collector import _mock_mesa_response

    cases = build_canonical_scope_test_matrix()

    def evil_executor(case):
        resp = _mock_mesa_response(case)
        if "scope_audit" in resp:
            resp["scope_audit"]["requested_scope"][
                "principal_id"
            ] = "principal-forged-evil"
        return resp

    with pytest.raises(MESAContractIntegrityError, match="principal mismatch"):
        collect_phase7_scope_isolation(
            run_id="RUN-ADV",
            run_dir=tmp_path / "RUN-ADV",
            mesa_sha="a" * 40,
            test_cases=cases,
            mesa_executor=evil_executor,
        )


def test_adversarial_b11_cross_run_stale_artifact_rejected(tmp_path) -> None:
    run_dir = tmp_path / "RUN-CURRENT-NEW"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-CURRENT-NEW")
    ctx = _adversarial_ctx(run_dir, run_id="RUN-CURRENT-NEW")

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["run_id"] = "RUN-STALE-OLD"
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    with pytest.raises(ProducerIntegrityError, match="(?i)run_id mismatch"):
        _b11(ctx)


def test_adversarial_b11_mesa_sha_mismatch_rejected(tmp_path) -> None:
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV", mesa_sha="b" * 40)
    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV", mesa_sha="a" * 40)
    with pytest.raises(ProducerIntegrityError, match="mesa_sha mismatch"):
        _b11(ctx)


def test_adversarial_b11_off_leaking_graph_paths_rejected(tmp_path) -> None:
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["pairs"][0]["off"]["paths"] = [
        {"graph_path_id": "leak", "path_valid": True}
    ]
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")
    with pytest.raises(ProducerIntegrityError, match="OFF pair leaked graph paths"):
        _b11(ctx)


def test_adversarial_b11_off_leaking_graph_origins_rejected(tmp_path) -> None:
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["pairs"][0]["off"]["top5_origins"] = [["graph"]]
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")
    with pytest.raises(
        ProducerIntegrityError, match="OFF pair leaked graph origins in top-5"
    ):
        _b11(ctx)


def test_adversarial_b11_mutated_store_during_execution_blocks_b11(tmp_path) -> None:
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")

    # Update raw state proof with mutated post composite fingerprint
    state_file = run_dir / "raw" / "state" / "state-proof.json"
    s_payload = json.loads(state_file.read_text(encoding="utf-8"))
    s_payload["post_composite_fingerprint"] = "sha256:" + "f" * 64
    s_payload["retrieval_state_unchanged"] = False
    s_bytes = (json.dumps(s_payload, sort_keys=True) + "\n").encode("utf-8")
    state_file.write_bytes(s_bytes)
    import hashlib

    s_sha = hashlib.sha256(s_bytes).hexdigest()
    state_file.with_suffix(".json.SHA256").write_text(f"{s_sha}  {state_file.name}\n")

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["state_proof_sha256"] = s_sha
    payload["frozen_state_proof"]["post_composite_fingerprint"] = "sha256:" + "f" * 64
    payload["frozen_state_proof"]["retrieval_state_unchanged"] = False
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")
    obs = _b11(ctx)
    assert obs.execution == "BLOCKED"
    assert obs.reason.startswith("BLOCKED_BY_RUNTIME_STATE_PROOF:")
    assert "composite store fingerprint mutated" in obs.reason


def test_adversarial_b11_pair_identity_mismatch_rejected(tmp_path) -> None:
    run_dir = tmp_path / "RUN-ADV"
    run_dir.mkdir()
    p = run_dir / "graph-ablation.json"
    _make_valid_graph_artifact(p, run_id="RUN-ADV")
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["pairs"][0]["off"]["pair_identity"] = "mismatched-pair-identity"
    p.unlink()
    p.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(p, payload)

    ctx = _adversarial_ctx(run_dir, run_id="RUN-ADV")
    with pytest.raises(ProducerIntegrityError, match="unmatched graph ON/OFF pair"):
        _b11(ctx)


def test_freeze_drift_in_authoritative_code_rejected(tmp_path) -> None:
    from harness.metric_producers import frozen_producer_code_sha256, produce_all
    from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze

    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    freeze_dir = repo / "freeze"
    freeze_dir.mkdir(parents=True, exist_ok=True)

    materials: dict[str, list[Path]] = {}
    for cat in sorted(MANDATORY_MATERIAL_CATEGORIES):
        p = freeze_dir / f"{cat}.txt"
        p.write_text(cat, encoding="utf-8")
        materials[cat] = [p]

    harness_dir = repo / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    harness_files = []
    for name in (
        "answer_execution.py",
        "artifacts.py",
        "execution_provenance.py",
        "metric_producers.py",
        "gates.py",
        "transaction.py",
        "scope_collector.py",
        "graph_collector.py",
        "state_proof.py",
        "mesa_adapters.py",
        "mesa_transport.py",
        "qualification_runner.py",
        "finalizer.py",
        "verdict.py",
    ):
        dest = harness_dir / name
        dest.write_text(
            (root / "harness" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
        harness_files.append(dest)
    materials["harness_source"] = harness_files

    scorer_dir = repo / "harness"
    scorer_files = []
    for name in ("retrieval_scorer.py", "answer_scorer.py", "official_scoring.py"):
        dest = scorer_dir / name
        dest.write_text(
            (root / "harness" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
        scorer_files.append(dest)
    materials["scorer_source"] = scorer_files

    gate_config = repo / "config" / "profile-b-gates.json"
    gate_config.parent.mkdir(parents=True, exist_ok=True)
    gate_config.write_text(
        (root / "config" / "profile-b-gates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    materials["thresholds"] = [gate_config]

    shas = {"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40}
    fp, cp = create_contract_freeze(
        output_dir=freeze_dir,
        run_id="RUN-DRIFT",
        repository_root=repo,
        repository_shas=shas,
        material_paths=materials,
        runtime_identities={"python": "3.13.12"},
    )

    ctx = ProducerContext(
        run_dir=repo,
        run_id="RUN-DRIFT",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas=shas,
        raw_manifest_hash="0" * 64,
        gate_config_path=gate_config,
    )

    # Mutate scope_collector.py in repo
    (harness_dir / "scope_collector.py").write_text(
        "# mutated scope collector\n", encoding="utf-8"
    )
    with pytest.raises(
        ProducerIntegrityError,
        match="producer execution source differs from frozen authority",
    ):
        frozen_producer_code_sha256(ctx)

    all_res = produce_all(ctx)
    assert all_res["B9"].execution == "BLOCKED"
    assert "authoritative producer code is not frozen" in all_res["B9"].reason


def test_qualification_runner_rejects_code_drift(tmp_path) -> None:
    from harness.qualification_runner import (
        QualificationConfig,
        run_profile_b_qualification,
    )
    from harness.qualification_runner import QualificationRunnerError
    from tests.test_qualification_runner import _setup_test_repo

    run_id = "RUN-DRIFT-QUAL"
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path, run_id=run_id)
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Drift the newly frozen trusted-transport boundary after freeze.
    (repo / "harness" / "mesa_transport.py").write_text(
        "# drift trusted MESA transport\n", encoding="utf-8"
    )

    config = QualificationConfig(
        run_id=run_id,
        run_dir=run_dir,
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
        gate_config_path=repo / "config" / "profile-b-gates.json",
    )

    with pytest.raises(
        QualificationRunnerError, match="Contract freeze verification failed"
    ):
        run_profile_b_qualification(config)
