"""Focused attacks against the official qualification trust root."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness.artifacts import RunArtifactStore
from harness.execution_provenance import (
    ExecutionProvenanceError,
    _begin_official_execution,
)
from harness.finalizer import ReleaseFinalizationError, finalize_release
from harness.gates import load_gate_config
from harness.graph_collector import execute_paired_graph_ablation
from harness.mesa_transport import MESATransportConfig, TrustedMESATransport
from harness.metric_producers import ProducerContext, ProducerIntegrityError, _b9, _b11
from harness.qualification_runner import QualificationConfig
from harness.scope_collector import collect_phase7_scope_isolation
from harness.state_proof import (
    RuntimeQuiescenceLease,
    acquire_runtime_quiescence,
    verify_quiescence_evidence,
)
from tests.independent_support import placeholder_sources
from tests.test_phase7_scope_collector import _mock_mesa_response
from tests.test_phase8_9_graph_and_state_proof import (
    MESA_SHA,
    _mock_graph_executor,
    _mock_identity_map,
    _mock_rel_queries,
    _setup_mock_stores,
)


def _ctx(run_dir: Path, manifest_hash: str) -> ProducerContext:
    return ProducerContext(
        run_dir=run_dir,
        run_id=run_dir.name,
        freeze_path=run_dir / "contract-freeze.json",
        checksum_path=run_dir / "contract-freeze.SHA256",
        repository_root=run_dir,
        current_repository_shas={"MESA": MESA_SHA},
        raw_manifest_hash=manifest_hash,
        gate_config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "profile-b-gates.json",
        execution_mode="official",
        execution_session=None,
    )


def _seal_manual_manifest(run_dir: Path) -> str:
    store = RunArtifactStore(run_dir, run_dir.name)
    manifest = store.compute_raw_manifest()
    store._write_immutable_json(run_dir / "raw-manifest.json", manifest)
    return str(manifest["manifest_hash"])


def test_fake_scope_raw_manifest_and_derived_chain_is_not_official(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "RUN-fake-scope"
    run_dir.mkdir()
    collect_phase7_scope_isolation(
        run_id=run_dir.name,
        run_dir=run_dir,
        mesa_sha=MESA_SHA,
        mesa_executor=lambda case: _mock_mesa_response(case, leak=False),
    )
    forged_scope = json.loads(
        (run_dir / "scope-isolation.json").read_text(encoding="utf-8")
    )
    assert (
        forged_scope["producer"]
        == "harness.scope_collector.collect_phase7_scope_isolation"
    )
    manifest_hash = _seal_manual_manifest(run_dir)
    with pytest.raises(
        ProducerIntegrityError, match="active official execution authority"
    ):
        _b9(_ctx(run_dir, manifest_hash))


def test_fake_graph_raw_manifest_state_and_derived_chain_is_not_official(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "RUN-fake-graph"
    run_dir.mkdir()
    stores = tmp_path / "stores"
    stores.mkdir()
    sqlite_path, lancedb_dir, kuzu_dir = _setup_mock_stores(stores)
    with acquire_runtime_quiescence(
        run_id=run_dir.name, sqlite_path=sqlite_path
    ) as lease:
        execute_paired_graph_ablation(
            run_id=run_dir.name,
            run_dir=run_dir,
            mesa_sha=MESA_SHA,
            rel_queries=_mock_rel_queries(),
            identity_map=_mock_identity_map(),
            sqlite_path=sqlite_path,
            lancedb_dir=lancedb_dir,
            kuzu_dir=kuzu_dir,
            mesa_executor=_mock_graph_executor,
            quiescence_lease=lease,
        )
    manifest_hash = _seal_manual_manifest(run_dir)
    with pytest.raises(
        ProducerIntegrityError, match="active official execution authority"
    ):
        _b11(_ctx(run_dir, manifest_hash))


@pytest.mark.parametrize(
    "claim",
    [
        {"runtime_freeze_verified": True},
        {"quiescence_verified": True},
        {
            "workers_stopped_or_read_only": True,
            "queues_drained": True,
            "no_pending_mutations": True,
        },
    ],
)
def test_caller_quiescence_booleans_never_create_authority(claim: dict) -> None:
    verified, reason = verify_quiescence_evidence(claim)
    assert verified is False
    assert "caller-supplied" in reason


def test_official_config_has_no_quiescence_result_fields(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="quiescence_verified"):
        QualificationConfig(
            run_id="RUN-config-attack",
            run_dir=tmp_path / "RUN-config-attack",
            freeze_path=tmp_path / "freeze.json",
            checksum_path=tmp_path / "freeze.SHA256",
            repository_root=tmp_path,
            current_repository_shas={},
            sqlite_path=tmp_path / "mesa.db",
            lancedb_dir=tmp_path / "lance",
            kuzu_dir=tmp_path / "kuzu",
            quiescence_verified=True,  # type: ignore[call-arg]
        )


def _transport() -> TrustedMESATransport:
    return TrustedMESATransport(
        MESATransportConfig(
            base_url="http://127.0.0.1:9",
            api_key="test-key",
            timeout_seconds=1.0,
            api_version="v4",
            expected_mesa_sha=MESA_SHA,
            runtime_profile="combined",
        )
    )


def _session(tmp_path: Path, run_id: str):
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    session = _begin_official_execution(
        run_id=run_id,
        run_dir=run_dir,
        freeze_sha256="f" * 64,
        mesa_sha=MESA_SHA,
        transport=_transport(),
    )
    session.write_execution_record()
    return session


def test_official_session_rejects_substituted_transport_implementation(
    tmp_path: Path,
) -> None:
    class SubstitutedTransport(TrustedMESATransport):
        pass

    substituted = SubstitutedTransport(
        MESATransportConfig(
            base_url="http://127.0.0.1:9",
            api_key="test-key",
            timeout_seconds=1.0,
            api_version="v4",
            expected_mesa_sha=MESA_SHA,
            runtime_profile="combined",
        )
    )
    run_dir = tmp_path / "RUN-substituted-transport"
    run_dir.mkdir()

    with pytest.raises(ExecutionProvenanceError, match="trusted MESA transport"):
        _begin_official_execution(
            run_id=run_dir.name,
            run_dir=run_dir,
            freeze_sha256="f" * 64,
            mesa_sha=MESA_SHA,
            transport=substituted,
        )


def _write_with_sidecar(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(path.suffix + ".SHA256").write_text(f"{digest}  {path.name}\n")


def test_copied_official_execution_record_is_rejected_cross_run(tmp_path: Path) -> None:
    source = _session(tmp_path, "RUN-source")
    target = _session(tmp_path, "RUN-target")
    copied = json.loads(
        (source.run_dir / "official-execution.json").read_text(encoding="utf-8")
    )
    target_path = target.run_dir / "official-execution.json"
    target_path.unlink()
    target_path.with_suffix(target_path.suffix + ".SHA256").unlink()
    _write_with_sidecar(target_path, copied)
    with pytest.raises(ExecutionProvenanceError, match="attestation mismatch"):
        target.verify_execution_record()


def test_copied_or_stale_raw_manifest_attestation_is_rejected(tmp_path: Path) -> None:
    source = _session(tmp_path, "RUN-manifest-source")
    target = _session(tmp_path, "RUN-manifest-target")
    source.start_capture()
    target.start_capture()
    copied = source.build_raw_manifest([])
    with pytest.raises(ExecutionProvenanceError, match="attestation mismatch"):
        target.verify_raw_manifest(copied, str(copied["manifest_hash"]))


def test_manually_rebuilt_current_run_manifest_cannot_recreate_attestation(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, "RUN-rebuilt-manifest")
    session.start_capture()
    manifest = session.build_raw_manifest([])
    manifest["execution_attestation"] = "0" * 64
    with pytest.raises(ExecutionProvenanceError, match="attestation mismatch"):
        session.verify_raw_manifest(manifest, str(manifest["manifest_hash"]))


def test_manual_state_proof_and_forged_lease_cannot_join_official_session(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, "RUN-manual-state")
    session.start_capture()
    state_path = session.run_dir / "raw" / "state" / "state-proof.json"
    state_path.parent.mkdir(parents=True)
    _write_with_sidecar(
        state_path,
        {
            "schema_version": "1.0",
            "run_id": session.run_id,
            "execution_id": session.execution_id,
            "quiescence_verified": True,
            "producer": "harness.state_proof.write_sealed_state_proof",
        },
    )

    class ForgedLease(RuntimeQuiescenceLease):
        def __init__(self) -> None:
            pass

        def is_held_for(self, _run_id: str) -> bool:
            return True

        def evidence(self) -> dict:
            return {"result": "QUIESCENT"}

    with pytest.raises(ExecutionProvenanceError, match="live trusted quiescence"):
        session.register_state_artifact(
            state_path,
            quiescence_lease=ForgedLease(),
            collector="harness.state_proof.write_sealed_state_proof",
        )


def test_finalizer_rejects_fully_consistent_test_mode_pass(tmp_path: Path) -> None:
    sources = placeholder_sources(tmp_path)
    config = load_gate_config(
        Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json"
    )
    answer_hash = hashlib.sha256(
        sources["answer-summary.json"].read_bytes()
    ).hexdigest()
    reference = f"answer-summary.json#sha256={answer_hash}"
    gates = []
    for gate_id in config.mandatory_gate_ids:
        definition = config.gates[gate_id]
        required = {
            key: value.model_dump(mode="json")
            for key, value in definition.requirements.items()
        }
        gates.append(
            {
                "schema_version": "1.0",
                "gate_id": gate_id,
                "hard": definition.hard,
                "execution_status": "COMPLETED",
                "status": "PASS",
                "required": required,
                "observed": {
                    key: requirement["value"] for key, requirement in required.items()
                },
                "reason": "forged_consistent_test_evidence",
                "evidence": [reference],
            }
        )
    gate_payload = json.loads(sources["gate-results.json"].read_text(encoding="utf-8"))
    gate_payload.update(
        {
            "final_verdict": "PROFILE_B_PASS_NATIVE",
            "mandatory_gate_ids": list(config.mandatory_gate_ids),
            "gates": gates,
        }
    )
    sources["gate-results.json"].write_text(json.dumps(gate_payload))
    run_manifest = json.loads(sources["run_manifest.json"].read_text())
    run_manifest.update(
        {
            "status": "PASS_NATIVE",
            "lifecycle_valid": True,
            "execution_mode": "test",
        }
    )
    sources["run_manifest.json"].write_text(json.dumps(run_manifest))

    with pytest.raises(
        ReleaseFinalizationError,
        match="active official qualification execution authority",
    ):
        finalize_release(
            run_id="RUN-independent",
            sources=sources,
            release_root=tmp_path / "release",
        )
