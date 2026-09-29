"""Controlled frozen Phase 7 corpus authority used only by tests."""

from __future__ import annotations

from typing import Any

from harness.scope_collector import (
    REQUIRED_SCOPE_CASE_IDS,
    ScopeTestCase,
    build_canonical_scope_test_matrix,
)


def build_synthetic_scope_test_matrix() -> list[ScopeTestCase]:
    """Build non-authoritative fixtures for isolated collector unit tests only."""

    fixtures = {
        case_id: [f"test-fixture-{case_id}"] for case_id in REQUIRED_SCOPE_CASE_IDS
    }
    return build_canonical_scope_test_matrix(
        authorized_tenant="tenant-auth",
        forbidden_tenant="tenant-forbidden",
        authorized_workspace="workspace-auth",
        authorized_dataset="dataset-auth",
        forbidden_dataset="dataset-forbidden",
        authorized_document="document-auth",
        authorized_agent="agent-auth",
        forbidden_agent="agent-forbidden",
        authorized_principal="principal-user-1",
        session_id="session-scope-test",
        case_evidence_fixtures=fixtures,
        fixture_authority_hash="0" * 64,
    )


def frozen_scope_fixture_authority(
    *, authorized_document: str = "doc-1"
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case_ids = {
        "cross_tenant_search": "scope-ev-cross-tenant",
        "cross_dataset_search": "scope-ev-cross-dataset",
        "cross_agent_search": "scope-ev-cross-agent",
        "inactive_status_search": "scope-ev-inactive",
        "wrong_jurisdiction_search": "scope-ev-wrong-jurisdiction",
        "stale_version_search": "scope-ev-stale",
        "effective_date_boundary_search": "scope-ev-expired",
        "context_visibility": "scope-chunk-context",
        "catalog_visibility": "scope-catalog-forbidden",
        "document_visibility": "scope-doc-forbidden",
        "revision_visibility": "scope-revision-forbidden",
        "chunk_visibility": "scope-chunk-forbidden",
    }
    corpus_fixtures: dict[str, dict[str, Any]] = {}
    identity_rows: list[dict[str, Any]] = []

    for case_id, fixture_id in case_ids.items():
        source_chunk_id = f"source-{case_id}"
        identity_type = {
            "context_visibility": "chunk",
            "catalog_visibility": "catalog",
            "document_visibility": "document",
            "revision_visibility": "revision",
            "chunk_visibility": "chunk",
        }.get(case_id, "evidence")
        mesa_chunk_id = (
            fixture_id
            if identity_type in {"evidence", "chunk"}
            else f"scope-chunk-{case_id}"
        )
        document_id = (
            fixture_id if identity_type == "document" else f"scope-doc-{case_id}"
        )
        revision_id = (
            fixture_id if identity_type == "revision" else f"scope-revision-{case_id}"
        )
        record: dict[str, Any] = {
            "identity_type": identity_type,
            "source_chunk_id": source_chunk_id,
            "tenant_id": "tenant-forbidden",
        }
        if case_id == "cross_dataset_search":
            record["dataset_id"] = "dataset-forbidden"
        if case_id == "cross_agent_search":
            record["agent_id"] = "agent-forbidden"
        if case_id == "inactive_status_search":
            record["status"] = "TOMBSTONED"
        if case_id == "wrong_jurisdiction_search":
            record["jurisdiction"] = "US"
        if case_id == "stale_version_search":
            record["is_current"] = False
        if case_id == "effective_date_boundary_search":
            record.update(
                {
                    "valid_from": "2025-01-01T00:00:00Z",
                    "valid_to": "2025-12-31T23:59:59Z",
                }
            )
        identity_rows.append(
            {
                "mesa_chunk_id": mesa_chunk_id,
                "source_chunk_id": source_chunk_id,
                "content_hash": "4" * 64,
                "delivery_state": "COMMITTED",
                "evidence_id": fixture_id if identity_type == "evidence" else None,
                "catalog_id": fixture_id if identity_type == "catalog" else None,
                "document_id": document_id,
                "remote_mutation_id": f"mutation-{case_id}",
                "version_id": revision_id,
                **{
                    key: value
                    for key, value in record.items()
                    if key not in {"identity_type", "source_chunk_id"}
                },
            }
        )
        corpus_fixtures[fixture_id] = record

    authority = {
        "forbidden_tenant": "tenant-forbidden",
        "forbidden_dataset": "dataset-forbidden",
        "forbidden_agent": "agent-forbidden",
        "authorized_document": authorized_document,
        "case_evidence_fixtures": {
            case_id: [fixture_id] for case_id, fixture_id in case_ids.items()
        },
        "corpus_fixtures": corpus_fixtures,
    }
    return authority, identity_rows
