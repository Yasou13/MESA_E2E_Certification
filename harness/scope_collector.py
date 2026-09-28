"""Authoritative Phase 7 Runtime Scope-Isolation Collector.

Executes and verifies the 12-case negative scope and ACL matrix against the
native MESA V4 contract, proving that cross-tenant, cross-dataset, cross-agent,
inactive, and temporal candidates are excluded pre-rank and zero forbidden
evidence leaks to the caller.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from harness.artifacts import canonical_json_bytes
from harness.mesa_adapters import (
    MESAContractIntegrityError,
    normalize_search_response,
    require_phase7_scope_contract,
)
from harness.metric_producers import write_sealed_measurement
from harness.mesa_transport import TrustedMESAResponse

if TYPE_CHECKING:
    from harness.execution_provenance import OfficialExecutionSession


REQUIRED_SCOPE_CASE_IDS = (
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
)

PHASE7_PRODUCER_IDENTITY = "harness.scope_collector.collect_phase7_scope_isolation"
PHASE7_CONTRACT_VERSION = "mesa.scope-audit.v1"


class ScopeTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    endpoint: str = "POST /v4/memory/search"
    request_payload: dict[str, Any]
    expected_tenant_id: str
    expected_agent_id: str
    expected_principal_id: str
    forbidden_evidence_ids: list[str] = Field(default_factory=list)
    forbidden_tenant_ids: list[str] = Field(default_factory=list)
    forbidden_agent_ids: list[str] = Field(default_factory=list)
    forbidden_dataset_ids: list[str] = Field(default_factory=list)


def build_canonical_scope_test_matrix(
    *,
    authorized_tenant: str = "tenant-auth",
    forbidden_tenant: str = "tenant-forbidden",
    authorized_workspace: str = "workspace-auth",
    authorized_dataset: str = "dataset-auth",
    forbidden_dataset: str = "dataset-forbidden",
    authorized_document: str = "document-auth",
    authorized_agent: str = "agent-auth",
    forbidden_agent: str = "agent-forbidden",
    authorized_principal: str = "principal-user-1",
    session_id: str = "session-scope-test",
) -> list[ScopeTestCase]:
    """Construct the canonical 12-case negative scope audit matrix."""

    base_search = {
        "session_id": session_id,
        "dataset_ids": [authorized_dataset],
        "query": "pre-rank isolation test query",
        "limit": 5,
    }

    cases = [
        ScopeTestCase(
            case_id="cross_tenant_search",
            endpoint="POST /v4/memory/search",
            request_payload=dict(base_search),
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"ev-{forbidden_tenant}-001"],
            forbidden_tenant_ids=[forbidden_tenant],
        ),
        ScopeTestCase(
            case_id="cross_dataset_search",
            endpoint="POST /v4/memory/search",
            request_payload=dict(base_search),
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"ev-{forbidden_dataset}-001"],
            forbidden_dataset_ids=[forbidden_dataset],
        ),
        ScopeTestCase(
            case_id="cross_agent_search",
            endpoint="POST /v4/memory/search",
            request_payload=dict(base_search),
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"ev-{forbidden_agent}-001"],
            forbidden_agent_ids=[forbidden_agent],
        ),
        ScopeTestCase(
            case_id="inactive_status_search",
            endpoint="POST /v4/memory/search",
            request_payload=dict(base_search),
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=["ev-inactive-tombstoned-001"],
        ),
        ScopeTestCase(
            case_id="wrong_jurisdiction_search",
            endpoint="POST /v4/memory/search",
            request_payload={**base_search, "jurisdiction": "TR"},
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=["ev-jurisdiction-us-001"],
        ),
        ScopeTestCase(
            case_id="stale_version_search",
            endpoint="POST /v4/memory/search",
            request_payload=dict(base_search),
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=["ev-stale-rev0-001"],
        ),
        ScopeTestCase(
            case_id="effective_date_boundary_search",
            endpoint="POST /v4/memory/search",
            request_payload={
                **base_search,
                "valid_at": "2026-06-01T00:00:00Z",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": "2026-12-31T23:59:59Z",
            },
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=["ev-expired-2025-001"],
        ),
        ScopeTestCase(
            case_id="context_visibility",
            endpoint="GET /v4/sessions/{session_id}/context",
            request_payload={"session_id": session_id, "token_budget": 2048},
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"chunk-{forbidden_tenant}-ctx"],
        ),
        ScopeTestCase(
            case_id="catalog_visibility",
            endpoint="GET /v4/catalog/workspaces",
            request_payload={"tenant_id": authorized_tenant},
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"catalog-{forbidden_tenant}"],
        ),
        ScopeTestCase(
            case_id="document_visibility",
            endpoint="GET /v4/catalog/documents",
            request_payload={
                "tenant_id": authorized_tenant,
                "workspace_id": authorized_workspace,
                "dataset_id": authorized_dataset,
            },
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"doc-{forbidden_tenant}"],
        ),
        ScopeTestCase(
            case_id="revision_visibility",
            endpoint="GET /v4/catalog/revisions",
            request_payload={
                "tenant_id": authorized_tenant,
                "workspace_id": authorized_workspace,
                "dataset_id": authorized_dataset,
                "document_id": authorized_document,
            },
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"rev-{forbidden_tenant}"],
        ),
        ScopeTestCase(
            case_id="chunk_visibility",
            endpoint="GET /v4/sessions/{session_id}/context",
            request_payload={
                "session_id": session_id,
                "query": "source chunk visibility probe",
                "token_budget": 2048,
            },
            expected_tenant_id=authorized_tenant,
            expected_agent_id=authorized_agent,
            expected_principal_id=authorized_principal,
            forbidden_evidence_ids=[f"chunk-{forbidden_tenant}"],
        ),
    ]
    return cases


def collect_phase7_scope_isolation(
    *,
    run_id: str,
    run_dir: Path | str,
    mesa_sha: str,
    test_cases: list[ScopeTestCase] | None = None,
    mesa_executor: (
        Callable[[ScopeTestCase], dict[str, Any] | TrustedMESAResponse] | None
    ) = None,
    api_version: str = "v4",
    execution_session: "OfficialExecutionSession | None" = None,
) -> Path:
    """Execute Phase 7 scope evaluation, verify pre-rank audit, and seal artifact."""

    run_path = Path(run_dir)
    cases = test_cases or build_canonical_scope_test_matrix()
    case_ids = {c.case_id for c in cases}
    if case_ids != set(REQUIRED_SCOPE_CASE_IDS):
        raise ValueError(
            f"scope test cases must match required 12-case matrix: {set(REQUIRED_SCOPE_CASE_IDS) - case_ids}"
        )

    if mesa_executor is None:
        raise RuntimeError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: live MESA executor not supplied for Phase 7 execution"
        )

    negative_cases_evidence: list[dict[str, Any]] = []
    total_eval = 0
    total_excl = 0
    total_elig = 0
    total_leaks = 0

    raw_scope_dir = run_path / "raw" / "scope"
    raw_scope_dir.mkdir(parents=True, exist_ok=True)

    for case in cases:
        exchange = mesa_executor(case)
        receipt: TrustedMESAResponse | None = None
        if isinstance(exchange, TrustedMESAResponse):
            receipt = exchange
            raw_response = exchange.payload
        else:
            raw_response = exchange
        if execution_session is not None and receipt is None:
            raise RuntimeError(
                "official Phase 7 execution requires trusted MESA transport receipts"
            )
        if not isinstance(raw_response, dict):
            raise MESAContractIntegrityError(
                f"case {case.case_id} response must be a dict"
            )

        resp_bytes = canonical_json_bytes(raw_response)
        resp_hash = hashlib.sha256(resp_bytes).hexdigest()

        # Persist sealed raw scope execution artifact for lineage validation
        raw_scope_path = raw_scope_dir / f"{case.case_id}.json"
        raw_scope_record = {
            "schema_version": "1.0",
            "run_id": run_id,
            "lane": "scope",
            "case_id": case.case_id,
            "endpoint": case.endpoint,
            "request": case.request_payload,
            "response": raw_response,
            "response_sha256": resp_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        if execution_session is not None:
            raw_scope_record["execution_id"] = execution_session.execution_id
        serialized_raw = (
            json.dumps(
                raw_scope_record,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        raw_scope_path.write_bytes(serialized_raw)
        raw_file_sha = hashlib.sha256(serialized_raw).hexdigest()
        raw_scope_path.with_suffix(raw_scope_path.suffix + ".SHA256").write_text(
            f"{raw_file_sha}  {raw_scope_path.name}\n", encoding="utf-8", newline="\n"
        )
        source_rel_path = f"raw/scope/{case.case_id}.json"
        if execution_session is not None and receipt is not None:
            execution_session.register_transport_artifact(
                raw_scope_path,
                receipt=receipt,
                request=case.request_payload,
                response=raw_response,
                collector=PHASE7_PRODUCER_IDENTITY,
            )

        if case.endpoint.startswith("POST /v4/memory/search"):
            capture = normalize_search_response(
                run_id=run_id,
                query_id=case.case_id,
                request=case.request_payload,
                response=raw_response,
                api_version=api_version,
                mesa_sha=mesa_sha,
            )
            require_phase7_scope_contract(capture)

            audit = capture.scope_audit
            if audit is None:
                raise MESAContractIntegrityError(
                    f"case {case.case_id} response missing scope_audit"
                )

            req_scope = audit.requested_scope
            if req_scope.get("tenant_id") != case.expected_tenant_id:
                raise MESAContractIntegrityError(
                    f"case {case.case_id} tenant mismatch: {req_scope.get('tenant_id')} != {case.expected_tenant_id}"
                )
            if req_scope.get("agent_id") != case.expected_agent_id:
                raise MESAContractIntegrityError(
                    f"case {case.case_id} agent mismatch: {req_scope.get('agent_id')} != {case.expected_agent_id}"
                )
            if req_scope.get("principal_id") != case.expected_principal_id:
                raise MESAContractIntegrityError(
                    f"case {case.case_id} principal mismatch: {req_scope.get('principal_id')} != {case.expected_principal_id}"
                )

            # Audit count coherency
            if audit.evaluated_candidate_count != (
                audit.excluded_candidate_count + audit.eligible_candidate_count
            ):
                raise MESAContractIntegrityError(
                    f"case {case.case_id} scope audit counts are incoherent"
                )

            returned_ids: list[str] = []
            returned_forbidden: list[str] = []

            for result in capture.results:
                ev_id = result.matched_evidence_id
                returned_ids.append(ev_id)
                # Leakage checks
                if ev_id in case.forbidden_evidence_ids:
                    returned_forbidden.append(ev_id)
                if result.scope.tenant_id in case.forbidden_tenant_ids:
                    returned_forbidden.append(ev_id)
                if result.scope.agent_id in case.forbidden_agent_ids:
                    returned_forbidden.append(ev_id)
                if result.scope.dataset_id in case.forbidden_dataset_ids:
                    returned_forbidden.append(ev_id)

            total_eval += audit.evaluated_candidate_count
            total_excl += audit.excluded_candidate_count
            total_elig += audit.eligible_candidate_count
            total_leaks += len(returned_forbidden)

            negative_cases_evidence.append(
                {
                    "case_id": case.case_id,
                    "proof_type": "search_pre_rank_scope",
                    "endpoint": case.endpoint,
                    "requested_scope": req_scope,
                    "requested_principal_id": case.expected_principal_id,
                    "evaluated_candidate_count": audit.evaluated_candidate_count,
                    "excluded_candidate_count": audit.excluded_candidate_count,
                    "eligible_candidate_count": audit.eligible_candidate_count,
                    "exclusion_audit_hash": audit.exclusion_audit_hash,
                    "returned_evidence_ids": returned_ids,
                    "returned_forbidden_evidence_ids": sorted(set(returned_forbidden)),
                    "pre_rank_audit_verified": True,
                    "source_raw_artifact": source_rel_path,
                    "source_raw_sha256": raw_file_sha,
                    "raw_response_sha256": resp_hash,
                }
            )
        else:
            # Non-search visibility / context endpoints
            # Check for forbidden items in response - genuine endpoint visibility proof, no synthetic pre-rank audit
            resp_str = json.dumps(raw_response, ensure_ascii=False)
            returned_forbidden = [
                f_id for f_id in case.forbidden_evidence_ids if f_id in resp_str
            ]
            total_leaks += len(returned_forbidden)

            negative_cases_evidence.append(
                {
                    "case_id": case.case_id,
                    "proof_type": "endpoint_visibility",
                    "endpoint": case.endpoint,
                    "requested_scope": {
                        "tenant_id": case.expected_tenant_id,
                        "agent_id": case.expected_agent_id,
                        "principal_id": case.expected_principal_id,
                    },
                    "requested_principal_id": case.expected_principal_id,
                    "evaluated_candidate_count": None,
                    "excluded_candidate_count": None,
                    "eligible_candidate_count": None,
                    "exclusion_audit_hash": None,
                    "returned_evidence_ids": [],
                    "returned_forbidden_evidence_ids": sorted(set(returned_forbidden)),
                    "pre_rank_audit_verified": False,
                    "endpoint_visibility_verified": len(returned_forbidden) == 0,
                    "source_raw_artifact": source_rel_path,
                    "source_raw_sha256": raw_file_sha,
                    "raw_response_sha256": resp_hash,
                }
            )

    payload = {
        "schema_version": "2.0",
        "run_id": run_id,
        "contract_version": PHASE7_CONTRACT_VERSION,
        "mesa_sha": mesa_sha,
        "mesa_contract_capabilities": {
            "candidate_scope_identity": True,
            "pre_rank_exclusion_audit": True,
        },
        "producer": PHASE7_PRODUCER_IDENTITY,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_evaluated_candidates": total_eval,
        "total_excluded_candidates": total_excl,
        "total_eligible_candidates": total_elig,
        "total_forbidden_leakage": total_leaks,
        "negative_cases": negative_cases_evidence,
    }
    if execution_session is not None:
        payload.update(execution_session.public_binding())

    target_path = run_path / "scope-isolation.json"
    write_sealed_measurement(target_path, payload)
    if execution_session is not None:
        execution_session.register_derived_artifact(
            target_path,
            artifact_type="scope_isolation",
            source_raw_paths=[f"raw/scope/{case.case_id}.json" for case in cases],
        )
    return target_path
