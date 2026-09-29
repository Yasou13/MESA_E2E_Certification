"""Tests for authoritative Phase 7 Scope-Isolation Collector and B9/B10 binding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.artifacts import RunArtifactStore
from harness.mesa_adapters import MESAContractIntegrityError
from harness.metric_producers import (
    ProducerContext,
    ProducerIntegrityError,
    _b9,
    write_sealed_measurement,
)
from harness.scope_collector import (
    ScopeTestCase,
    collect_phase7_scope_isolation,
)
from tests.scope_fixture_support import build_synthetic_scope_test_matrix


RUN_ID = "RUN-phase7-test"
MESA_SHA = "a" * 40


def _mock_mesa_response(
    case: ScopeTestCase,
    *,
    leak: bool = False,
    incoherent_counts: bool = False,
    invalid_hash: bool = False,
) -> dict:
    if not case.endpoint.startswith("POST /v4/memory/search"):
        # non-search endpoint mock
        return {
            "session_id": "session-scope-test",
            "dataset_ids": [case.expected_tenant_id],
            "results": [],
            "items": [],
        }

    eval_c = 10
    excl_c = 8 if not incoherent_counts else 3
    elig_c = 2

    # If leak is True, return forbidden evidence
    ev_id = (
        case.forbidden_evidence_ids[0]
        if (leak and case.forbidden_evidence_ids)
        else f"ev-valid-{case.case_id}-001"
    )

    matched = {
        "assertion_id": ev_id,
        "tenant_id": case.expected_tenant_id if not leak else "tenant-forbidden",
        "dataset_id": "dataset-auth",
        "document_id": "doc-1",
        "revision_id": "rev-1",
        "chunk_id": f"chunk-{ev_id}",
        "status": "ACTIVE",
        "jurisdiction": "TR",
        "valid_from": "2026-01-01",
        "valid_to": "",
        "evidence_span": "legal rule",
    }

    result = {
        "candidate_id": ev_id,
        "evidence_id": ev_id,
        "assertion_id": ev_id,
        "source_chunk_id": f"chunk-{ev_id}",
        "document_id": "doc-1",
        "evidence_span": "legal rule",
        "raw_score": 0.5,
        "rrf_score": 0.5,
        "legal_factor": 1.0,
        "final_score": 0.5,
        "provenance": [matched],
        "matched_assertions": [matched],
        "supporting_assertions": [],
        "retrieval_provenance": {"origins": ["vector"], "graph_paths": []},
        "scope_identity": {
            "tenant_id": case.expected_tenant_id if not leak else "tenant-forbidden",
            "dataset_id": "dataset-auth",
            "agent_id": case.expected_agent_id if not leak else "agent-forbidden",
            "jurisdiction": "TR",
            "status": "ACTIVE",
        },
    }

    audit_hash = "sha256:" + "f" * 64 if not invalid_hash else "bad-hash"

    return {
        "session_id": "session-scope-test",
        "dataset_ids": ["dataset-auth"],
        "results": [result],
        "scope_audit": {
            "contract_version": "mesa.scope-audit.v1",
            "enforcement_stage": "pre_rank",
            "requested_scope": {
                "tenant_id": case.expected_tenant_id,
                "agent_id": case.expected_agent_id,
                "principal_id": case.expected_principal_id,
                "dataset_ids": ["dataset-auth"],
                "jurisdiction": None,
                "valid_at": None,
                "valid_from": None,
                "valid_to": None,
            },
            "requested_scope_identity": "scope-id-1",
            "query_identity": f"query-{case.case_id}",
            "evaluated_candidate_count": eval_c,
            "excluded_candidate_count": excl_c,
            "eligible_candidate_count": elig_c,
            "exclusion_audit_hash": audit_hash,
        },
    }


def _dummy_ctx(run_dir: Path) -> ProducerContext:
    freeze_path = run_dir / "contract-freeze.json"
    freeze_path.write_text(
        json.dumps(
            {
                "run_id": RUN_ID,
                "repository_shas": {"MESA": MESA_SHA},
                "materials": [],
                "runtime_identities": {},
            }
        )
    )
    store = RunArtifactStore(run_dir, run_id=RUN_ID)
    manifest_info = store.compute_raw_manifest()
    store._write_immutable_json(run_dir / "raw-manifest.json", manifest_info)
    return ProducerContext(
        run_dir=run_dir,
        run_id=RUN_ID,
        freeze_path=freeze_path,
        checksum_path=run_dir / "SHA256SUMS.txt",
        repository_root=run_dir,
        current_repository_shas={"MESA": MESA_SHA},
        raw_manifest_hash=manifest_info["manifest_hash"],
        gate_config_path=run_dir / "profile-b-gates.json",
    )


def test_canonical_visibility_cases_use_real_mesa_v4_read_contracts() -> None:
    cases = {case.case_id: case for case in build_synthetic_scope_test_matrix()}

    assert cases["context_visibility"].endpoint == (
        "GET /v4/sessions/{session_id}/context"
    )
    assert cases["catalog_visibility"].endpoint == "GET /v4/catalog/workspaces"
    assert cases["document_visibility"].endpoint == "GET /v4/catalog/documents"
    assert cases["revision_visibility"].endpoint == "GET /v4/catalog/revisions"
    assert cases["chunk_visibility"].endpoint == (
        "GET /v4/sessions/{session_id}/context"
    )
    assert cases["document_visibility"].request_payload == {
        "tenant_id": "tenant-auth",
        "workspace_id": "workspace-auth",
        "dataset_id": "dataset-auth",
    }
    assert cases["revision_visibility"].request_payload["document_id"] == (
        "document-auth"
    )


def test_phase7_collector_end_to_end(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    def executor(case: ScopeTestCase) -> dict:
        return _mock_mesa_response(case, leak=False)

    artifact_path = collect_phase7_scope_isolation(
        run_id=RUN_ID,
        run_dir=run_dir,
        mesa_sha=MESA_SHA,
        test_cases=build_synthetic_scope_test_matrix(),
        mesa_executor=executor,
    )
    assert artifact_path.is_file()
    assert (run_dir / "scope-isolation.json.SHA256").is_file()

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["contract_version"] == "mesa.scope-audit.v1"
    assert (
        payload["producer"] == "harness.scope_collector.collect_phase7_scope_isolation"
    )
    assert payload["total_forbidden_leakage"] == 0
    assert len(payload["negative_cases"]) == 12

    ctx = _dummy_ctx(run_dir)
    obs = _b9(ctx)
    assert obs.execution == "COMPLETED"
    assert obs.observed["cross_tenant_scope_leakage"] == 0
    assert obs.observed["isolation_acl_passed"] is True


def test_phase7_collector_detects_forbidden_leak(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    def executor(case: ScopeTestCase) -> dict:
        # Leak on the cross_tenant_search case
        return _mock_mesa_response(case, leak=(case.case_id == "cross_tenant_search"))

    artifact_path = collect_phase7_scope_isolation(
        run_id=RUN_ID,
        run_dir=run_dir,
        mesa_sha=MESA_SHA,
        test_cases=build_synthetic_scope_test_matrix(),
        mesa_executor=executor,
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["total_forbidden_leakage"] > 0

    ctx = _dummy_ctx(run_dir)
    obs = _b9(ctx)
    assert obs.execution == "COMPLETED"
    assert obs.observed["cross_tenant_scope_leakage"] > 0
    assert obs.observed["isolation_acl_passed"] is False


def test_phase7_collector_rejects_incoherent_audit_counts(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    def executor(case: ScopeTestCase) -> dict:
        return _mock_mesa_response(case, incoherent_counts=True)

    with pytest.raises(MESAContractIntegrityError, match="incoherent"):
        collect_phase7_scope_isolation(
            run_id=RUN_ID,
            run_dir=run_dir,
            mesa_sha=MESA_SHA,
            test_cases=build_synthetic_scope_test_matrix(),
            mesa_executor=executor,
        )


def test_phase7_collector_rejects_invalid_audit_hash(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    def executor(case: ScopeTestCase) -> dict:
        return _mock_mesa_response(case, invalid_hash=True)

    with pytest.raises(MESAContractIntegrityError, match="exclusion_audit_hash"):
        collect_phase7_scope_isolation(
            run_id=RUN_ID,
            run_dir=run_dir,
            mesa_sha=MESA_SHA,
            test_cases=build_synthetic_scope_test_matrix(),
            mesa_executor=executor,
        )


def test_b9_rejects_caller_forged_producer(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    def executor(case: ScopeTestCase) -> dict:
        return _mock_mesa_response(case, leak=False)

    collect_phase7_scope_isolation(
        run_id=RUN_ID,
        run_dir=run_dir,
        mesa_sha=MESA_SHA,
        test_cases=build_synthetic_scope_test_matrix(),
        mesa_executor=executor,
    )

    path = run_dir / "scope-isolation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["producer"] = "caller-forged-producer"
    path.unlink()
    path.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(path, payload)

    ctx = _dummy_ctx(run_dir)
    with pytest.raises(ProducerIntegrityError, match="producer lineage"):
        _b9(ctx)


def test_b9_rejects_unsupported_contract_version(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    def executor(case: ScopeTestCase) -> dict:
        return _mock_mesa_response(case, leak=False)

    collect_phase7_scope_isolation(
        run_id=RUN_ID,
        run_dir=run_dir,
        mesa_sha=MESA_SHA,
        test_cases=build_synthetic_scope_test_matrix(),
        mesa_executor=executor,
    )

    path = run_dir / "scope-isolation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["contract_version"] = "mesa.scope-audit.v999"
    path.unlink()
    path.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(path, payload)

    ctx = _dummy_ctx(run_dir)
    with pytest.raises(
        ProducerIntegrityError, match="unsupported scope contract_version"
    ):
        _b9(ctx)
