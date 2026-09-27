"""Strict adapters for the verified public MESA V4 retrieval/context surfaces.

The adapter deliberately distinguishes fields returned by MESA from facts that
would have to be inferred.  Missing certification fields are reported as
contract blockers; they are never synthesized from request scope or debug
provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


MESA_SEARCH_CONTRACT = "POST /v4/memory/search"
MESA_CONTEXT_CONTRACT = "GET /v4/sessions/{session_id}/context"
NORMALIZED_RETRIEVAL_SCHEMA = "mesa-e2e.retrieval.v1"
NORMALIZED_CONTEXT_SCHEMA = "mesa-e2e.context.v1"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class MESAContractIntegrityError(ValueError):
    """A supplied native response contradicts the verified contract."""


class MESAContractBlocker(MESAContractIntegrityError):
    """MESA does not expose evidence needed for a certification assertion."""

    def __init__(self, blocker_id: str, missing_capabilities: list[str]):
        self.blocker_id = blocker_id
        self.missing_capabilities = tuple(sorted(set(missing_capabilities)))
        super().__init__(
            f"{blocker_id}: missing native MESA capabilities: "
            + ", ".join(self.missing_capabilities)
        )


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MESAContractIntegrityError(f"non-canonical JSON value: {exc}") from exc


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MESAContractIntegrityError(f"{field} must be a non-empty string")
    return value


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MESAContractIntegrityError(f"{field} must be numeric")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise MESAContractIntegrityError(f"{field} must be finite")
    return number


class NormalizedScopeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    dataset_id: str
    document_id: str
    revision_id: str
    chunk_id: str
    status: str
    jurisdiction: str
    valid_from: str
    valid_to: str
    agent_id: str | None = None
    principal_id: str | None = None
    pre_rank_scope_audit_id: str | None = None


class NormalizedGraphPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stable_path_id: str | None = None
    assertion_ids: list[str]
    entity_ids: list[str]
    edge_directions: list[str]
    predicates: list[str]
    seed_id: str
    score: float


class NormalizedRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(ge=1)
    public_result_id: str
    matched_evidence_id: str
    mesa_chunk_id: str
    document_id: str
    evidence_text: str = Field(max_length=4096)
    raw_score: float | None
    rrf_score: float
    final_score: float
    matched_evidence: dict[str, Any]
    support_provenance: list[dict[str, Any]]
    debug_provenance: dict[str, Any]
    scope: NormalizedScopeEvidence
    graph_paths: list[NormalizedGraphPath]


class NormalizedRetrievalCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = NORMALIZED_RETRIEVAL_SCHEMA
    run_id: str
    query_id: str
    source_contract: str = MESA_SEARCH_CONTRACT
    source_api_version: str
    mesa_sha: str
    session_id: str
    dataset_ids: list[str]
    query: str
    response_sha256: str
    results: list[NormalizedRetrievalResult]


class NormalizedContextCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = NORMALIZED_CONTEXT_SCHEMA
    run_id: str
    query_id: str
    source_contract: str = MESA_CONTEXT_CONTRACT
    source_api_version: str
    mesa_sha: str
    tenant_id: str
    agent_id: str
    session_id: str
    dataset_ids: list[str]
    exact_model_visible_context: str
    context_evidence_ids: list[str]
    context_sha256: str
    canonical_memories_sha256: str


def _validate_contract_identity(*, api_version: str, mesa_sha: str) -> None:
    if api_version != "v4":
        raise MESAContractIntegrityError(
            f"unsupported MESA capability api_version: {api_version!r}"
        )
    if _GIT_SHA.fullmatch(mesa_sha) is None:
        raise MESAContractIntegrityError("mesa_sha must be a full Git SHA")


def _normalize_scope(matched: dict[str, Any], result: dict[str, Any]) -> NormalizedScopeEvidence:
    return NormalizedScopeEvidence(
        tenant_id=_nonempty(matched.get("tenant_id"), "matched_assertion.tenant_id"),
        dataset_id=_nonempty(matched.get("dataset_id"), "matched_assertion.dataset_id"),
        document_id=_nonempty(
            matched.get("document_id") or result.get("document_id"),
            "matched_assertion.document_id",
        ),
        revision_id=_nonempty(matched.get("revision_id"), "matched_assertion.revision_id"),
        chunk_id=_nonempty(matched.get("chunk_id"), "matched_assertion.chunk_id"),
        status=_nonempty(matched.get("status"), "matched_assertion.status"),
        jurisdiction=str(matched.get("jurisdiction") or ""),
        valid_from=str(matched.get("valid_from") or ""),
        valid_to=str(matched.get("valid_to") or ""),
        agent_id=matched.get("agent_id"),
        principal_id=matched.get("principal_id"),
        pre_rank_scope_audit_id=matched.get("pre_rank_scope_audit_id"),
    )


def _normalize_graph_paths(
    debug: dict[str, Any], *, available_assertion_ids: set[str]
) -> list[NormalizedGraphPath]:
    raw_paths = debug.get("graph_paths", [])
    if not isinstance(raw_paths, list):
        raise MESAContractIntegrityError("retrieval_provenance.graph_paths must be a list")
    normalized: list[NormalizedGraphPath] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for index, raw in enumerate(raw_paths):
        if not isinstance(raw, dict):
            raise MESAContractIntegrityError(f"graph path {index} must be an object")
        assertion_ids = raw.get("assertion_ids")
        entity_ids = raw.get("entity_ids")
        directions = raw.get("edge_directions")
        predicates = raw.get("predicates")
        if not all(isinstance(value, list) for value in (assertion_ids, entity_ids, directions, predicates)):
            raise MESAContractIntegrityError(f"graph path {index} has malformed arrays")
        if not assertion_ids or len(entity_ids) != len(assertion_ids) + 1:
            raise MESAContractIntegrityError(f"graph path {index} has invalid hop alignment")
        if len(directions) != len(assertion_ids) or len(predicates) != len(assertion_ids):
            raise MESAContractIntegrityError(f"graph path {index} has invalid edge alignment")
        if any(direction not in {"forward", "reverse"} for direction in directions):
            raise MESAContractIntegrityError(f"graph path {index} has invalid direction")
        if not set(assertion_ids).issubset(available_assertion_ids):
            raise MESAContractIntegrityError(
                f"graph path {index} references an assertion outside matched/support provenance"
            )
        key = (tuple(entity_ids), tuple(assertion_ids))
        if key in seen:
            raise MESAContractIntegrityError("duplicate graph path cannot amplify support")
        seen.add(key)
        normalized.append(
            NormalizedGraphPath(
                stable_path_id=raw.get("graph_path_id"),
                assertion_ids=[_nonempty(v, "graph assertion ID") for v in assertion_ids],
                entity_ids=[_nonempty(v, "graph entity ID") for v in entity_ids],
                edge_directions=list(directions),
                predicates=[_nonempty(v, "graph predicate") for v in predicates],
                seed_id=_nonempty(raw.get("seed_id"), "graph seed_id"),
                score=_finite_number(raw.get("score"), "graph score"),
            )
        )
    return normalized


def normalize_search_response(
    *,
    run_id: str,
    query_id: str,
    request: dict[str, Any],
    response: dict[str, Any],
    api_version: str,
    mesa_sha: str,
) -> NormalizedRetrievalCapture:
    """Normalize the verified MESA 0.7.1 V4 public search response."""

    _validate_contract_identity(api_version=api_version, mesa_sha=mesa_sha)
    if not isinstance(response, dict) or not isinstance(response.get("results"), list):
        raise MESAContractIntegrityError("MESA search response must contain results[]")
    session_id = _nonempty(response.get("session_id"), "response.session_id")
    if request.get("session_id") != session_id:
        raise MESAContractIntegrityError("request/response session_id mismatch")
    query = _nonempty(request.get("query"), "request.query")
    response_datasets = response.get("dataset_ids")
    if not isinstance(response_datasets, list) or not response_datasets:
        raise MESAContractIntegrityError("response.dataset_ids must be non-empty")
    if any(not isinstance(item, str) or not item for item in response_datasets):
        raise MESAContractIntegrityError("response.dataset_ids contains an invalid ID")
    requested_datasets = request.get("dataset_ids")
    if requested_datasets is not None and list(requested_datasets) != response_datasets:
        raise MESAContractIntegrityError("request/response dataset_ids mismatch")

    normalized: list[NormalizedRetrievalResult] = []
    public_ids: set[str] = set()
    evidence_ids: set[str] = set()
    for rank, result in enumerate(response["results"], start=1):
        if not isinstance(result, dict):
            raise MESAContractIntegrityError(f"result at rank {rank} must be an object")
        public_id = _nonempty(result.get("candidate_id"), "candidate_id")
        evidence_id = _nonempty(result.get("evidence_id"), "evidence_id")
        assertion_id = _nonempty(result.get("assertion_id"), "assertion_id")
        chunk_id = _nonempty(result.get("source_chunk_id"), "source_chunk_id")
        if evidence_id != assertion_id:
            raise MESAContractIntegrityError(
                f"result at rank {rank} has conflicting evidence/assertion identity"
            )
        if public_id in public_ids or evidence_id in evidence_ids:
            raise MESAContractIntegrityError("duplicate ranked result/evidence identity")
        public_ids.add(public_id)
        evidence_ids.add(evidence_id)

        matched = result.get("matched_assertions")
        support = result.get("supporting_assertions")
        provenance = result.get("provenance")
        debug = result.get("retrieval_provenance")
        if not isinstance(matched, list) or len(matched) != 1 or not isinstance(matched[0], dict):
            raise MESAContractIntegrityError(
                f"result at rank {rank} must expose exactly one first-class matched assertion"
            )
        if not isinstance(support, list) or any(not isinstance(item, dict) for item in support):
            raise MESAContractIntegrityError(f"result at rank {rank} has malformed support provenance")
        if not isinstance(provenance, list) or any(not isinstance(item, dict) for item in provenance):
            raise MESAContractIntegrityError(f"result at rank {rank} has malformed provenance")
        if not isinstance(debug, dict):
            raise MESAContractIntegrityError(f"result at rank {rank} has malformed retrieval_provenance")

        matched_item = matched[0]
        if matched_item.get("assertion_id") != evidence_id:
            raise MESAContractIntegrityError("matched assertion does not own ranked evidence ID")
        if matched_item.get("chunk_id") != chunk_id:
            raise MESAContractIntegrityError("matched assertion chunk differs from ranked source_chunk_id")
        support_ids = [item.get("assertion_id") for item in support]
        if evidence_id in support_ids or len(support_ids) != len(set(support_ids)):
            raise MESAContractIntegrityError("support provenance conflicts or duplicates matched evidence")
        provenance_ids = [item.get("assertion_id") for item in provenance]
        if provenance_ids.count(evidence_id) != 1 or set(provenance_ids) != {evidence_id, *support_ids}:
            raise MESAContractIntegrityError("provenance does not equal matched plus support assertions")

        available_assertions = {evidence_id, *[_nonempty(v, "support assertion ID") for v in support_ids]}
        graph_paths = _normalize_graph_paths(
            debug, available_assertion_ids=available_assertions
        )
        evidence_text = str(result.get("evidence_span") or "")
        if len(evidence_text) > 4096:
            raise MESAContractIntegrityError("evidence span exceeds MESA V4 bounded contract")
        normalized.append(
            NormalizedRetrievalResult(
                rank=rank,
                public_result_id=public_id,
                matched_evidence_id=evidence_id,
                mesa_chunk_id=chunk_id,
                document_id=_nonempty(result.get("document_id"), "document_id"),
                evidence_text=evidence_text,
                raw_score=(
                    _finite_number(result["raw_score"], "raw_score")
                    if result.get("raw_score") is not None
                    else None
                ),
                rrf_score=_finite_number(result.get("rrf_score"), "rrf_score"),
                final_score=_finite_number(result.get("final_score"), "final_score"),
                matched_evidence=dict(matched_item),
                support_provenance=[dict(item) for item in support],
                debug_provenance=dict(debug),
                scope=_normalize_scope(matched_item, result),
                graph_paths=graph_paths,
            )
        )

    return NormalizedRetrievalCapture(
        run_id=_nonempty(run_id, "run_id"),
        query_id=_nonempty(query_id, "query_id"),
        source_api_version=api_version,
        mesa_sha=mesa_sha,
        session_id=session_id,
        dataset_ids=list(response_datasets),
        query=query,
        response_sha256=hashlib.sha256(_canonical_bytes(response)).hexdigest(),
        results=normalized,
    )


def require_phase7_scope_contract(capture: NormalizedRetrievalCapture) -> None:
    """Require fields that current public MESA does not yet expose.

    Request/session scope must not be copied onto candidates as proof.  The
    current MESA response omits candidate agent/principal identity and a
    native pre-rank exclusion audit token, so this must remain a blocker.
    """

    missing: set[str] = set()
    for item in capture.results:
        if not item.scope.agent_id:
            missing.add("candidate.agent_id")
        if not item.scope.principal_id:
            missing.add("candidate.principal_id")
        if not item.scope.pre_rank_scope_audit_id:
            missing.add("candidate.pre_rank_scope_audit_id")
    if missing:
        raise MESAContractBlocker("WAIT_FOR_MESA_PHASE_7", sorted(missing))


def require_phase8_9_graph_contract(capture: NormalizedRetrievalCapture) -> None:
    """Require stable graph paths and native ON/OFF pairing evidence."""

    missing: set[str] = {"native_graph_on_off_execution_identity"}
    for item in capture.results:
        for path in item.graph_paths:
            if not path.stable_path_id:
                missing.add("graph_path_id")
    raise MESAContractBlocker("WAIT_FOR_MESA_PHASE_8_9", sorted(missing))


def normalize_context_response(
    *,
    run_id: str,
    query_id: str,
    response: dict[str, Any],
    api_version: str,
    mesa_sha: str,
) -> NormalizedContextCapture:
    """Capture the exact post-budget ContextBuilder string returned publicly."""

    _validate_contract_identity(api_version=api_version, mesa_sha=mesa_sha)
    required = ("tenant_id", "agent_id", "session_id", "dataset_ids", "context", "canonical_memories")
    missing = [field for field in required if field not in response]
    if missing:
        raise MESAContractIntegrityError(f"context response missing fields: {missing}")
    memories = response["canonical_memories"]
    if not isinstance(memories, list) or any(not isinstance(item, dict) for item in memories):
        raise MESAContractIntegrityError("canonical_memories must be a list of objects")
    evidence_ids: list[str] = []
    for index, memory in enumerate(memories):
        chunk_id = memory.get("source_chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise MESAContractIntegrityError(
                f"model-visible memory {index} has no first-class source_chunk_id"
            )
        if chunk_id in evidence_ids:
            raise MESAContractIntegrityError("duplicate model-visible context evidence ID")
        evidence_ids.append(chunk_id)
    context = response["context"]
    if not isinstance(context, str):
        raise MESAContractIntegrityError("context must be the exact rendered string")
    datasets = response["dataset_ids"]
    if not isinstance(datasets, list) or any(not isinstance(v, str) or not v for v in datasets):
        raise MESAContractIntegrityError("context dataset_ids are malformed")
    return NormalizedContextCapture(
        run_id=_nonempty(run_id, "run_id"),
        query_id=_nonempty(query_id, "query_id"),
        source_api_version=api_version,
        mesa_sha=mesa_sha,
        tenant_id=_nonempty(response["tenant_id"], "tenant_id"),
        agent_id=_nonempty(response["agent_id"], "agent_id"),
        session_id=_nonempty(response["session_id"], "session_id"),
        dataset_ids=list(datasets),
        exact_model_visible_context=context,
        context_evidence_ids=evidence_ids,
        context_sha256=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        canonical_memories_sha256=hashlib.sha256(_canonical_bytes(memories)).hexdigest(),
    )
