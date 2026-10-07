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
SEALED_RETRIEVAL_CONTEXT_CONTRACT = "mesa-e2e.sealed-retrieval-context.v1"
NORMALIZED_RETRIEVAL_SCHEMA = "mesa-e2e.retrieval.v1"
NORMALIZED_CONTEXT_SCHEMA = "mesa-e2e.context.v1"
SEALED_RETRIEVAL_CONTEXT_SCHEMA = "mesa-e2e.context.v2"
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


class NormalizedScopeAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: str
    enforcement_stage: str
    requested_scope: dict[str, Any]
    requested_scope_identity: str
    query_identity: str
    evaluated_candidate_count: int = Field(ge=0)
    excluded_candidate_count: int = Field(ge=0)
    eligible_candidate_count: int = Field(ge=0)
    exclusion_audit_hash: str


class NormalizedGraphAblation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: str
    mode: str
    pair_identity: str
    query_identity: str
    retrieval_config_identity: str
    scope_identity: str


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
    retrieval_limit: int = Field(gt=0)
    response_sha256: str
    results: list[NormalizedRetrievalResult]
    scope_audit: NormalizedScopeAudit | None = None
    graph_ablation: NormalizedGraphAblation | None = None


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
    retrieval_response_sha256: str
    allowed_retrieval_evidence_ids: list[str]
    candidate_bindings: list[dict[str, Any]]


def _validate_contract_identity(*, api_version: str, mesa_sha: str) -> None:
    if api_version != "v4":
        raise MESAContractIntegrityError(
            f"unsupported MESA capability api_version: {api_version!r}"
        )
    if _GIT_SHA.fullmatch(mesa_sha) is None:
        raise MESAContractIntegrityError("mesa_sha must be a full Git SHA")


def _normalize_scope(
    matched: dict[str, Any], result: dict[str, Any]
) -> NormalizedScopeEvidence:
    scope_id = result.get("scope_identity")
    if scope_id is not None and not isinstance(scope_id, dict):
        raise MESAContractIntegrityError("result.scope_identity must be an object")
    scope_id = scope_id or {}
    tenant_id = matched.get("tenant_id") or scope_id.get("tenant_id")
    dataset_id = matched.get("dataset_id") or scope_id.get("dataset_id")
    doc_id = matched.get("document_id") or result.get("document_id")
    rev_id = matched.get("revision_id") or scope_id.get("revision_id")
    chunk_id = matched.get("chunk_id") or result.get("source_chunk_id")
    status = matched.get("status") or scope_id.get("status")
    jurisdiction = str(
        matched.get("jurisdiction")
        if matched.get("jurisdiction") is not None
        else (scope_id.get("jurisdiction") or "")
    )
    valid_from = str(matched.get("valid_from") or "")
    valid_to = str(matched.get("valid_to") or "")
    agent_id = matched.get("agent_id") or scope_id.get("agent_id")
    principal_id = matched.get("principal_id") or scope_id.get("principal_id")
    pre_rank_audit_id = (
        matched.get("pre_rank_scope_audit_id")
        or result.get("pre_rank_scope_audit_id")
    )
    return NormalizedScopeEvidence(
        tenant_id=_nonempty(tenant_id, "matched_assertion.tenant_id"),
        dataset_id=_nonempty(dataset_id, "matched_assertion.dataset_id"),
        document_id=_nonempty(doc_id, "matched_assertion.document_id"),
        revision_id=_nonempty(rev_id or "r-1", "matched_assertion.revision_id"),
        chunk_id=_nonempty(chunk_id, "matched_assertion.chunk_id"),
        status=_nonempty(status or "ACTIVE", "matched_assertion.status"),
        jurisdiction=jurisdiction,
        valid_from=valid_from,
        valid_to=valid_to,
        agent_id=agent_id,
        principal_id=principal_id,
        pre_rank_scope_audit_id=pre_rank_audit_id,
    )


def _normalize_graph_paths(
    debug: dict[str, Any], *, available_assertion_ids: set[str]
) -> list[NormalizedGraphPath]:
    raw_paths = debug.get("graph_paths", [])
    if not isinstance(raw_paths, list):
        raise MESAContractIntegrityError(
            "retrieval_provenance.graph_paths must be a list"
        )
    normalized: list[NormalizedGraphPath] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for index, raw in enumerate(raw_paths):
        if not isinstance(raw, dict):
            raise MESAContractIntegrityError(f"graph path {index} must be an object")
        assertion_ids = raw.get("assertion_ids")
        entity_ids = raw.get("entity_ids")
        directions = raw.get("edge_directions")
        predicates = raw.get("predicates")
        if not all(
            isinstance(value, list)
            for value in (assertion_ids, entity_ids, directions, predicates)
        ):
            raise MESAContractIntegrityError(f"graph path {index} has malformed arrays")
        if not assertion_ids or len(entity_ids) != len(assertion_ids) + 1:
            raise MESAContractIntegrityError(
                f"graph path {index} has invalid hop alignment"
            )
        if len(directions) != len(assertion_ids) or len(predicates) != len(
            assertion_ids
        ):
            raise MESAContractIntegrityError(
                f"graph path {index} has invalid edge alignment"
            )
        if any(direction not in {"forward", "reverse"} for direction in directions):
            raise MESAContractIntegrityError(
                f"graph path {index} has invalid direction"
            )
        if not set(assertion_ids).issubset(available_assertion_ids):
            raise MESAContractIntegrityError(
                f"graph path {index} references an assertion outside matched/support provenance"
            )
        key = (tuple(entity_ids), tuple(assertion_ids))
        if key in seen:
            raise MESAContractIntegrityError(
                "duplicate graph path cannot amplify support"
            )
        seen.add(key)
        normalized.append(
            NormalizedGraphPath(
                stable_path_id=raw.get("graph_path_id"),
                assertion_ids=[
                    _nonempty(v, "graph assertion ID") for v in assertion_ids
                ],
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
    retrieval_limit = request.get("limit")
    if (
        isinstance(retrieval_limit, bool)
        or not isinstance(retrieval_limit, int)
        or retrieval_limit <= 0
    ):
        raise MESAContractIntegrityError("request.limit must be a positive integer")
    if len(response["results"]) > retrieval_limit:
        raise MESAContractIntegrityError(
            "MESA search response exceeds the requested retrieval limit"
        )
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
            raise MESAContractIntegrityError(
                "duplicate ranked result/evidence identity"
            )
        public_ids.add(public_id)
        evidence_ids.add(evidence_id)

        matched = result.get("matched_assertions")
        support = result.get("supporting_assertions")
        provenance = result.get("provenance")
        debug = result.get("retrieval_provenance")
        if (
            not isinstance(matched, list)
            or len(matched) != 1
            or not isinstance(matched[0], dict)
        ):
            raise MESAContractIntegrityError(
                f"result at rank {rank} must expose exactly one first-class matched assertion"
            )
        if not isinstance(support, list) or any(
            not isinstance(item, dict) for item in support
        ):
            raise MESAContractIntegrityError(
                f"result at rank {rank} has malformed support provenance"
            )
        if not isinstance(provenance, list) or any(
            not isinstance(item, dict) for item in provenance
        ):
            raise MESAContractIntegrityError(
                f"result at rank {rank} has malformed provenance"
            )
        if not isinstance(debug, dict):
            raise MESAContractIntegrityError(
                f"result at rank {rank} has malformed retrieval_provenance"
            )

        matched_item = matched[0]
        if matched_item.get("assertion_id") != evidence_id:
            raise MESAContractIntegrityError(
                "matched assertion does not own ranked evidence ID"
            )
        if matched_item.get("chunk_id") != chunk_id:
            raise MESAContractIntegrityError(
                "matched assertion chunk differs from ranked source_chunk_id"
            )
        support_ids = [item.get("assertion_id") for item in support]
        if evidence_id in support_ids or len(support_ids) != len(set(support_ids)):
            raise MESAContractIntegrityError(
                "support provenance conflicts or duplicates matched evidence"
            )
        provenance_ids = [item.get("assertion_id") for item in provenance]
        if provenance_ids.count(evidence_id) != 1 or set(provenance_ids) != {
            evidence_id,
            *support_ids,
        }:
            raise MESAContractIntegrityError(
                "provenance does not equal matched plus support assertions"
            )

        available_assertions = {
            evidence_id,
            *[_nonempty(v, "support assertion ID") for v in support_ids],
        }
        graph_paths = _normalize_graph_paths(
            debug, available_assertion_ids=available_assertions
        )
        evidence_text = str(result.get("evidence_span") or "")
        if len(evidence_text) > 4096:
            raise MESAContractIntegrityError(
                "evidence span exceeds MESA V4 bounded contract"
            )
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

    scope_audit_model: NormalizedScopeAudit | None = None
    raw_scope_audit = response.get("scope_audit")
    if raw_scope_audit is not None:
        if not isinstance(raw_scope_audit, dict):
            raise MESAContractIntegrityError("scope_audit must be an object")
        if raw_scope_audit.get("contract_version") != "mesa.scope-audit.v1":
            raise MESAContractIntegrityError(
                f"unsupported scope_audit contract_version: {raw_scope_audit.get('contract_version')!r}"
            )
        if raw_scope_audit.get("enforcement_stage") != "pre_rank":
            raise MESAContractIntegrityError("scope_audit must enforce pre_rank stage")
        eval_c = raw_scope_audit.get("evaluated_candidate_count")
        excl_c = raw_scope_audit.get("excluded_candidate_count")
        elig_c = raw_scope_audit.get("eligible_candidate_count")
        if (
            isinstance(eval_c, bool)
            or isinstance(excl_c, bool)
            or isinstance(elig_c, bool)
            or not isinstance(eval_c, int)
            or not isinstance(excl_c, int)
            or not isinstance(elig_c, int)
            or eval_c < 0
            or excl_c < 0
            or elig_c < 0
            or eval_c != excl_c + elig_c
        ):
            raise MESAContractIntegrityError("scope_audit counts are incoherent")
        hash_val = raw_scope_audit.get("exclusion_audit_hash")
        if not isinstance(hash_val, str) or not hash_val.startswith("sha256:"):
            raise MESAContractIntegrityError("scope_audit exclusion_audit_hash is invalid")
        req_scope = raw_scope_audit.get("requested_scope")
        if not isinstance(req_scope, dict) or not req_scope.get("principal_id"):
            raise MESAContractIntegrityError("scope_audit requested_scope missing principal_id")
        scope_audit_model = NormalizedScopeAudit(
            contract_version=str(raw_scope_audit["contract_version"]),
            enforcement_stage=str(raw_scope_audit["enforcement_stage"]),
            requested_scope=dict(req_scope),
            requested_scope_identity=_nonempty(
                raw_scope_audit.get("requested_scope_identity"),
                "scope_audit.requested_scope_identity",
            ),
            query_identity=_nonempty(
                raw_scope_audit.get("query_identity"), "scope_audit.query_identity"
            ),
            evaluated_candidate_count=eval_c,
            excluded_candidate_count=excl_c,
            eligible_candidate_count=elig_c,
            exclusion_audit_hash=hash_val,
        )

    graph_ablation_model: NormalizedGraphAblation | None = None
    raw_graph_ablation = response.get("graph_ablation")
    if raw_graph_ablation is not None:
        if not isinstance(raw_graph_ablation, dict):
            raise MESAContractIntegrityError("graph_ablation must be an object")
        if raw_graph_ablation.get("contract_version") != "mesa.graph-ablation.v1":
            raise MESAContractIntegrityError(
                f"unsupported graph_ablation contract_version: {raw_graph_ablation.get('contract_version')!r}"
            )
        mode = raw_graph_ablation.get("mode")
        if mode not in {"enabled", "disabled"}:
            raise MESAContractIntegrityError(
                f"graph_ablation mode must be enabled or disabled: {mode!r}"
            )
        graph_ablation_model = NormalizedGraphAblation(
            contract_version=str(raw_graph_ablation["contract_version"]),
            mode=mode,
            pair_identity=_nonempty(
                raw_graph_ablation.get("pair_identity"), "graph_ablation.pair_identity"
            ),
            query_identity=_nonempty(
                raw_graph_ablation.get("query_identity"), "graph_ablation.query_identity"
            ),
            retrieval_config_identity=_nonempty(
                raw_graph_ablation.get("retrieval_config_identity"),
                "graph_ablation.retrieval_config_identity",
            ),
            scope_identity=_nonempty(
                raw_graph_ablation.get("scope_identity"), "graph_ablation.scope_identity"
            ),
        )

    return NormalizedRetrievalCapture(
        run_id=_nonempty(run_id, "run_id"),
        query_id=_nonempty(query_id, "query_id"),
        source_api_version=api_version,
        mesa_sha=mesa_sha,
        session_id=session_id,
        dataset_ids=list(response_datasets),
        query=query,
        retrieval_limit=retrieval_limit,
        response_sha256=hashlib.sha256(_canonical_bytes(response)).hexdigest(),
        results=normalized,
        scope_audit=scope_audit_model,
        graph_ablation=graph_ablation_model,
    )


def require_phase7_scope_contract(capture: NormalizedRetrievalCapture) -> None:
    """Verify that native Phase 7 scope identity and pre-rank audit contract are satisfied.

    Candidate ownership must expose agent_id (via scope_identity.agent_id),
    request scope must expose principal_id (via scope_audit.requested_scope.principal_id),
    and a native pre-rank exclusion audit token must be present and coherent.
    """

    missing: set[str] = set()
    if capture.scope_audit is None:
        missing.add("candidate.pre_rank_scope_audit_id")
        missing.add("scope_audit")
    else:
        req_scope = capture.scope_audit.requested_scope
        if not req_scope.get("principal_id"):
            missing.add("requested_scope.principal_id")
        if not capture.scope_audit.exclusion_audit_hash:
            missing.add("scope_audit.exclusion_audit_hash")

    for item in capture.results:
        if not item.scope.agent_id:
            missing.add("candidate.agent_id")

    if missing:
        raise MESAContractBlocker("WAIT_FOR_MESA_PHASE_7", sorted(missing))


def require_phase8_9_graph_contract(capture: NormalizedRetrievalCapture) -> None:
    """Require stable graph paths and native ON/OFF pairing evidence."""

    missing: set[str] = set()
    if capture.graph_ablation is None:
        missing.add("native_graph_on_off_execution_identity")
    for item in capture.results:
        for path in item.graph_paths:
            if not path.stable_path_id:
                missing.add("graph_path_id")
    if missing:
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
    required = (
        "tenant_id",
        "agent_id",
        "session_id",
        "dataset_ids",
        "context",
        "canonical_memories",
    )
    missing = [field for field in required if field not in response]
    if missing:
        raise MESAContractIntegrityError(f"context response missing fields: {missing}")
    memories = response["canonical_memories"]
    if not isinstance(memories, list) or any(
        not isinstance(item, dict) for item in memories
    ):
        raise MESAContractIntegrityError("canonical_memories must be a list of objects")
    evidence_ids: list[str] = []
    for index, memory in enumerate(memories):
        chunk_id = memory.get("source_chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise MESAContractIntegrityError(
                f"model-visible memory {index} has no first-class source_chunk_id"
            )
        if chunk_id in evidence_ids:
            raise MESAContractIntegrityError(
                "duplicate model-visible context evidence ID"
            )
        evidence_ids.append(chunk_id)
    context = response["context"]
    if not isinstance(context, str):
        raise MESAContractIntegrityError("context must be the exact rendered string")
    datasets = response["dataset_ids"]
    if not isinstance(datasets, list) or any(
        not isinstance(v, str) or not v for v in datasets
    ):
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
        canonical_memories_sha256=hashlib.sha256(
            _canonical_bytes(memories)
        ).hexdigest(),
        retrieval_response_sha256=hashlib.sha256(
            _canonical_bytes(memories)
        ).hexdigest(),
        allowed_retrieval_evidence_ids=list(evidence_ids),
        candidate_bindings=[
            {
                "rank": index,
                "source_chunk_id": source_chunk_id,
                "included": True,
                "rejection_reason": None,
            }
            for index, source_chunk_id in enumerate(evidence_ids, start=1)
        ],
    )


def build_sealed_retrieval_context(
    capture: NormalizedRetrievalCapture,
    *,
    token_budget: int,
    tenant_id: str | None = None,
    agent_id: str | None = None,
) -> NormalizedContextCapture:
    """Build official answer context only from the sealed ranked retrieval capture.

    The formatting is deterministic and the budget is enforced conservatively at
    four UTF-8 bytes per token.  Every ranked candidate remains in the
    provenance table even when the context budget rejects it.
    """

    if token_budget <= 0:
        raise MESAContractIntegrityError("context token_budget must be positive")
    result_tenants = {result.scope.tenant_id for result in capture.results}
    result_agents = {
        result.scope.agent_id
        for result in capture.results
        if result.scope.agent_id is not None
    }
    if len(result_tenants) > 1 or (
        tenant_id is not None and result_tenants and result_tenants != {tenant_id}
    ):
        raise MESAContractIntegrityError(
            "retrieval candidate tenant scope contradicts answer context scope"
        )
    if len(result_agents) > 1 or (
        agent_id is not None and result_agents and result_agents != {agent_id}
    ):
        raise MESAContractIntegrityError(
            "retrieval candidate agent scope contradicts answer context scope"
        )
    resolved_tenant = tenant_id or next(iter(result_tenants), None)
    resolved_agent = agent_id or next(iter(result_agents), "NO_AGENT")
    if not resolved_tenant:
        raise MESAContractIntegrityError(
            "answer context tenant scope must be explicit when retrieval has no candidates"
        )
    max_bytes = token_budget * 4
    rendered: list[str] = []
    bindings: list[dict[str, Any]] = []
    included_ids: list[str] = []
    used_bytes = 0

    for result in capture.results:
        origins = result.debug_provenance.get("origins", [])
        if not isinstance(origins, list) or any(
            not isinstance(origin, str) or not origin for origin in origins
        ):
            raise MESAContractIntegrityError(
                f"retrieval candidate at rank {result.rank} has invalid origins"
            )
        block_payload = {
            "rank": result.rank,
            "candidate_id": result.public_result_id,
            "evidence_id": result.matched_evidence_id,
            "assertion_id": result.matched_evidence_id,
            "source_chunk_id": result.mesa_chunk_id,
            "document_id": result.document_id,
            "retrieval_origins": origins,
            "evidence_text": result.evidence_text,
        }
        block = json.dumps(
            block_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        separator_bytes = 1 if rendered else 0
        block_bytes = len(block.encode("utf-8")) + separator_bytes
        included = used_bytes + block_bytes <= max_bytes
        if included:
            rendered.append(block)
            included_ids.append(result.mesa_chunk_id)
            used_bytes += block_bytes
        bindings.append(
            {
                **block_payload,
                "included": included,
                "rejection_reason": None if included else "token_budget",
            }
        )

    exact_context = "\n".join(rendered)
    allowed_ids = [result.mesa_chunk_id for result in capture.results]
    return NormalizedContextCapture(
        schema_version=SEALED_RETRIEVAL_CONTEXT_SCHEMA,
        run_id=capture.run_id,
        query_id=capture.query_id,
        source_contract=SEALED_RETRIEVAL_CONTEXT_CONTRACT,
        source_api_version=capture.source_api_version,
        mesa_sha=capture.mesa_sha,
        tenant_id=resolved_tenant,
        agent_id=resolved_agent,
        session_id=capture.session_id,
        dataset_ids=list(capture.dataset_ids),
        exact_model_visible_context=exact_context,
        context_evidence_ids=included_ids,
        context_sha256=hashlib.sha256(exact_context.encode("utf-8")).hexdigest(),
        canonical_memories_sha256=hashlib.sha256(
            _canonical_bytes(bindings)
        ).hexdigest(),
        retrieval_response_sha256=capture.response_sha256,
        allowed_retrieval_evidence_ids=allowed_ids,
        candidate_bindings=bindings,
    )
