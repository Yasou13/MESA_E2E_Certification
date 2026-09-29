"""Canonical, fail-closed Profile B qualification runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from harness.answer_execution import (
    OpenAICompatibleHTTPTransport,
    execute_answer_and_persist,
)
from harness.artifacts import RunArtifactStore, canonical_json_bytes
from harness.execution_provenance import _begin_official_execution
from harness.freeze import FreezeStatus, verify_contract_freeze
from harness.graph_collector import execute_paired_graph_ablation
from harness.gt_governance import load_ground_truth, validate_ground_truth
from harness.identity import IdentityMap, UnknownIdentityError
from harness.mesa_transport import (
    MESATransportConfig,
    MESATransportError,
    TrustedMESATransport,
)
from harness.mesa_adapters import normalize_context_response
from harness.models import GroundTruthItem
from harness.official_scoring import (
    FrozenScoringAuthority,
    OfficialScoringError,
    ScoringAuthorityUnavailable,
    load_frozen_scoring_authority,
)
from harness.scope_collector import (
    REQUIRED_SCOPE_CASE_IDS,
    ScopeTestCase,
    build_canonical_scope_test_matrix,
    collect_phase7_scope_isolation,
)
from harness.state_proof import StateProofError, establish_paired_state_stability
from harness.transaction import CertificationTransaction, TransactionError


class QualificationRunnerError(RuntimeError):
    """Raised when official qualification cannot establish its authority chain."""


@dataclass(frozen=True)
class QualificationScope:
    tenant_id: str
    workspace_id: str
    dataset_ids: list[str]
    agent_id: str
    expected_principal: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "dataset_ids": list(self.dataset_ids),
            "agent_id": self.agent_id,
            "expected_principal": self.expected_principal,
        }


@dataclass(frozen=True)
class ScopeTestAuthority:
    forbidden_tenant: str
    forbidden_dataset: str
    forbidden_agent: str
    authorized_document: str
    case_evidence_fixtures: dict[str, list[str]]
    fixture_authority_hash: str


def _scope_fixture_error(message: str) -> QualificationRunnerError:
    return QualificationRunnerError(
        f"BLOCKED_BY_QUALIFICATION_SCOPE_FIXTURE: {message}"
    )


_CASE_FIXTURE_TYPES = {
    "cross_tenant_search": "evidence",
    "cross_dataset_search": "evidence",
    "cross_agent_search": "evidence",
    "inactive_status_search": "evidence",
    "wrong_jurisdiction_search": "evidence",
    "stale_version_search": "evidence",
    "effective_date_boundary_search": "evidence",
    "context_visibility": "chunk",
    "catalog_visibility": "catalog",
    "document_visibility": "document",
    "revision_visibility": "revision",
    "chunk_visibility": "chunk",
}


@dataclass(frozen=True)
class QualificationConfig:
    run_id: str
    run_dir: Path
    freeze_path: Path
    checksum_path: Path
    repository_root: Path
    current_repository_shas: dict[str, str]
    sqlite_path: Path
    lancedb_dir: Path
    kuzu_dir: Path
    mesa_base_url: str = ""
    mesa_api_key: str = ""
    mesa_timeout_seconds: float = 30.0
    mesa_runtime_profile: str = "combined"
    mesa_storage_root: Path | None = None
    gate_config_path: Path | None = None
    release_root: Path | None = None
    api_version: str = "v4"
    qualification_scope: QualificationScope | None = None
    answer_provider_base_url: str = ""
    answer_provider_api_key: str = ""
    answer_provider_timeout_seconds: float = 60.0
    answer_system_prompt: str = ""
    answer_instruction: str = ""
    answer_request_parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualificationResult:
    run_id: str
    final_verdict: str
    status: str
    raw_manifest_hash: str
    release_path: Path | None
    gate_results: list[dict[str, Any]]
    failure_reason: str | None = None


def _load_freeze(path: Path, run_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationRunnerError(f"cannot read contract freeze: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("run_id") != run_id:
        raise QualificationRunnerError("contract freeze run_id mismatch")
    return payload


def _trusted_transport_from_freeze(
    config: QualificationConfig, freeze: dict[str, Any]
) -> TrustedMESATransport:
    runtime = freeze.get("runtime_identities")
    authority = runtime.get("mesa_transport") if isinstance(runtime, dict) else None
    if not isinstance(authority, dict):
        raise QualificationRunnerError(
            "frozen trusted MESA transport authority is missing"
        )
    required = {
        "base_url",
        "api_version",
        "expected_mesa_sha",
        "implementation",
        "runtime_profile",
    }
    missing = sorted(required - authority.keys())
    if missing:
        raise QualificationRunnerError(
            f"frozen MESA transport authority is incomplete: {missing}"
        )
    expected_sha = config.current_repository_shas["MESA"]
    comparisons = {
        "base_url": config.mesa_base_url.rstrip("/"),
        "api_version": config.api_version,
        "expected_mesa_sha": expected_sha,
        "implementation": TrustedMESATransport.implementation_id,
        "runtime_profile": config.mesa_runtime_profile,
    }
    for identity_field, actual in comparisons.items():
        if authority.get(identity_field) != actual:
            raise QualificationRunnerError(
                f"MESA transport {identity_field} differs from frozen authority"
            )
    try:
        transport = TrustedMESATransport(
            MESATransportConfig(
                base_url=config.mesa_base_url,
                api_key=config.mesa_api_key,
                timeout_seconds=config.mesa_timeout_seconds,
                api_version=config.api_version,
                expected_mesa_sha=expected_sha,
                runtime_profile=config.mesa_runtime_profile,
            )
        )
        transport.preflight()
    except MESATransportError as exc:
        raise QualificationRunnerError(
            f"trusted MESA transport preflight failed: {exc}"
        ) from exc
    return transport


def _load_required_scoring_authority(
    config: QualificationConfig,
) -> tuple[
    FrozenScoringAuthority,
    list[GroundTruthItem],
    list[GroundTruthItem],
    IdentityMap,
]:
    try:
        authority = load_frozen_scoring_authority(
            freeze_path=config.freeze_path,
            repository_root=config.repository_root,
            run_id=config.run_id,
        )
        ground_truth = load_ground_truth(authority.ground_truth_path)
        identity_map = IdentityMap()
        identity_map.load_from_file(
            authority.identity_map_path,
            expected_sha256=authority.identity_map_sha256,
        )
        validation = validate_ground_truth(
            authority.ground_truth_path,
            authority.qrels_path,
            identity_map,
            split_name="TEST",
        )
        if validation.get("status") != "PASS":
            raise OfficialScoringError(
                f"frozen GT/qrels validation failed: {validation.get('errors')}"
            )
        relational = [item for item in ground_truth if item.query_class == "RELATIONAL"]
        if len(relational) != 10:
            raise OfficialScoringError(
                "official frozen authority must contain exactly 10 RELATIONAL "
                f"queries, got {len(relational)}"
            )
    except (
        ScoringAuthorityUnavailable,
        OfficialScoringError,
        OSError,
        ValueError,
    ) as exc:
        raise QualificationRunnerError(
            f"official frozen scoring authority unavailable: {exc}"
        ) from exc
    return authority, ground_truth, relational, identity_map


def _trusted_answer_transport(
    config: QualificationConfig,
    freeze: dict[str, Any],
    authority: FrozenScoringAuthority,
) -> OpenAICompatibleHTTPTransport:
    if authority.answer_provider != "openai_compatible":
        raise QualificationRunnerError(
            f"unsupported frozen answer provider: {authority.answer_provider!r}"
        )
    runtime = freeze.get("runtime_identities")
    transport_authority = (
        runtime.get("answer_transport") if isinstance(runtime, dict) else None
    )
    if not isinstance(transport_authority, dict):
        raise QualificationRunnerError("frozen answer transport authority is missing")
    expected_transport = {
        "base_url": config.answer_provider_base_url.rstrip("/"),
        "implementation": OpenAICompatibleHTTPTransport.implementation_id,
        "provider": authority.answer_provider,
    }
    for field_name, actual in expected_transport.items():
        if transport_authority.get(field_name) != actual:
            raise QualificationRunnerError(
                f"answer transport {field_name} differs from frozen authority"
            )
    expected_hashes = {
        "system_prompt_sha256": hashlib.sha256(
            config.answer_system_prompt.encode("utf-8")
        ).hexdigest(),
        "answer_instruction_sha256": hashlib.sha256(
            config.answer_instruction.encode("utf-8")
        ).hexdigest(),
        "request_parameters_sha256": hashlib.sha256(
            json.dumps(
                config.answer_request_parameters,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    for field_name, actual in expected_hashes.items():
        if getattr(authority, field_name) != actual:
            raise QualificationRunnerError(
                f"answer {field_name} differs from frozen authority"
            )
    try:
        return OpenAICompatibleHTTPTransport(
            base_url=config.answer_provider_base_url,
            api_key=config.answer_provider_api_key,
            timeout_seconds=config.answer_provider_timeout_seconds,
        )
    except ValueError as exc:
        raise QualificationRunnerError(
            f"invalid trusted answer transport: {exc}"
        ) from exc


def _load_frozen_scope_authority(
    freeze: dict[str, Any],
    identity_map: IdentityMap,
) -> tuple[QualificationScope, ScopeTestAuthority]:
    runtime = freeze.get("runtime_identities")
    if not isinstance(runtime, dict):
        raise _scope_fixture_error("contract freeze runtime_identities is missing")
    scope_dict = runtime.get("qualification_scope")
    if not isinstance(scope_dict, dict):
        raise _scope_fixture_error(
            "frozen qualification scope authority (runtime_identities.qualification_scope) is missing"
        )
    required_scope = {
        "tenant_id",
        "workspace_id",
        "dataset_ids",
        "agent_id",
        "expected_principal",
    }
    missing_scope = sorted(required_scope - scope_dict.keys())
    if missing_scope:
        raise _scope_fixture_error(
            f"frozen qualification scope authority is missing fields: {missing_scope}"
        )
    tenant_id = scope_dict["tenant_id"]
    workspace_id = scope_dict["workspace_id"]
    dataset_ids = scope_dict["dataset_ids"]
    agent_id = scope_dict["agent_id"]
    expected_principal = scope_dict["expected_principal"]
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise _scope_fixture_error("qualification scope tenant_id must be non-empty")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise _scope_fixture_error("qualification scope workspace_id must be non-empty")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise _scope_fixture_error("qualification scope agent_id must be non-empty")
    if not isinstance(expected_principal, str) or not expected_principal.strip():
        raise _scope_fixture_error(
            "qualification scope expected_principal must be non-empty"
        )
    if (
        not isinstance(dataset_ids, list)
        or not dataset_ids
        or any(not isinstance(d, str) or not d.strip() for d in dataset_ids)
    ):
        raise _scope_fixture_error(
            "qualification scope dataset_ids must be a non-empty list of strings"
        )
    if len(dataset_ids) != len(set(dataset_ids)):
        raise _scope_fixture_error("qualification scope dataset_ids contain duplicates")

    fixtures_dict = runtime.get("scope_test_authority")
    if not isinstance(fixtures_dict, dict):
        raise _scope_fixture_error(
            "frozen scope test authority (runtime_identities.scope_test_authority) is missing"
        )
    required_fixtures = {
        "forbidden_tenant",
        "forbidden_dataset",
        "forbidden_agent",
        "authorized_document",
        "case_evidence_fixtures",
        "corpus_fixtures",
    }
    missing_fixtures = sorted(required_fixtures - fixtures_dict.keys())
    if missing_fixtures:
        raise _scope_fixture_error(
            f"frozen scope test authority is missing fields: {missing_fixtures}"
        )
    forbidden_tenant = fixtures_dict["forbidden_tenant"]
    forbidden_dataset = fixtures_dict["forbidden_dataset"]
    forbidden_agent = fixtures_dict["forbidden_agent"]
    authorized_document = fixtures_dict["authorized_document"]
    case_evidence_fixtures = fixtures_dict["case_evidence_fixtures"]
    corpus_fixtures = fixtures_dict["corpus_fixtures"]
    if not isinstance(forbidden_tenant, str) or not forbidden_tenant.strip():
        raise _scope_fixture_error(
            "scope test authority forbidden_tenant must be non-empty"
        )
    if not isinstance(forbidden_dataset, str) or not forbidden_dataset.strip():
        raise _scope_fixture_error(
            "scope test authority forbidden_dataset must be non-empty"
        )
    if not isinstance(forbidden_agent, str) or not forbidden_agent.strip():
        raise _scope_fixture_error(
            "scope test authority forbidden_agent must be non-empty"
        )
    if not isinstance(authorized_document, str) or not authorized_document.strip():
        raise _scope_fixture_error(
            "scope test authority authorized_document must be non-empty"
        )
    if forbidden_tenant == tenant_id:
        raise _scope_fixture_error("forbidden tenant belongs to the allowed tenant")
    if forbidden_dataset in dataset_ids:
        raise _scope_fixture_error(
            "forbidden dataset belongs to the allowed dataset scope"
        )
    if forbidden_agent == agent_id:
        raise _scope_fixture_error("forbidden agent belongs to the allowed agent")
    if not identity_map.contains_document_id(authorized_document):
        raise _scope_fixture_error(
            f"authorized_document {authorized_document!r} is absent from the frozen identity map"
        )
    if not isinstance(case_evidence_fixtures, dict):
        raise _scope_fixture_error("case_evidence_fixtures must be an object")
    fixture_case_ids = set(case_evidence_fixtures)
    required_case_ids = set(REQUIRED_SCOPE_CASE_IDS)
    if fixture_case_ids != required_case_ids:
        missing = sorted(required_case_ids - fixture_case_ids)
        unknown = sorted(fixture_case_ids - required_case_ids)
        raise _scope_fixture_error(
            f"case_evidence_fixtures must cover exactly the supported cases; missing={missing}, unknown={unknown}"
        )
    normalized_case_fixtures: dict[str, list[str]] = {}
    all_fixture_ids: list[str] = []
    for case_id in REQUIRED_SCOPE_CASE_IDS:
        values = case_evidence_fixtures[case_id]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise _scope_fixture_error(
                f"case {case_id} requires at least one non-empty frozen fixture ID"
            )
        if len(values) != len(set(values)):
            raise _scope_fixture_error(f"case {case_id} contains duplicate fixture IDs")
        normalized_case_fixtures[case_id] = list(values)
        all_fixture_ids.extend(values)
    if len(all_fixture_ids) != len(set(all_fixture_ids)):
        raise _scope_fixture_error("fixture IDs must be unique across Phase 7 cases")
    if not isinstance(corpus_fixtures, dict):
        raise _scope_fixture_error("corpus_fixtures must be an object")
    if set(corpus_fixtures) != set(all_fixture_ids):
        missing = sorted(set(all_fixture_ids) - set(corpus_fixtures))
        unknown = sorted(set(corpus_fixtures) - set(all_fixture_ids))
        raise _scope_fixture_error(
            f"corpus fixture registry mismatch; missing={missing}, unreferenced={unknown}"
        )

    probe_time = datetime.fromisoformat("2026-06-01T00:00:00+00:00")
    for case_id, fixture_ids in normalized_case_fixtures.items():
        expected_type = _CASE_FIXTURE_TYPES[case_id]
        for fixture_id in fixture_ids:
            record = corpus_fixtures[fixture_id]
            if not isinstance(record, dict):
                raise _scope_fixture_error(
                    f"corpus fixture {fixture_id!r} must be an object"
                )
            identity_type = record.get("identity_type")
            source_chunk_id = record.get("source_chunk_id")
            if identity_type != expected_type:
                raise _scope_fixture_error(
                    f"fixture {fixture_id!r} has identity_type {identity_type!r}; case {case_id} requires {expected_type!r}"
                )
            if not isinstance(source_chunk_id, str) or not source_chunk_id:
                raise _scope_fixture_error(
                    f"fixture {fixture_id!r} lacks source_chunk_id corpus binding"
                )
            try:
                rows = identity_map.rows_for_identity(source_chunk_id)
            except UnknownIdentityError as exc:
                raise _scope_fixture_error(
                    f"fixture {fixture_id!r} references unknown frozen corpus identity {source_chunk_id!r}"
                ) from exc
            identity_fields = {
                "evidence": "evidence_id",
                "catalog": "catalog_id",
                "document": "document_id",
                "revision": "version_id",
            }
            if identity_type == "chunk":
                bound_rows = [
                    row
                    for row in rows
                    if fixture_id in {row.mesa_chunk_id, row.source_chunk_id}
                ]
            else:
                identity_field = identity_fields[identity_type]
                bound_rows = [
                    row for row in rows if getattr(row, identity_field) == fixture_id
                ]
            if not bound_rows:
                raise _scope_fixture_error(
                    f"{identity_type} fixture {fixture_id!r} is absent from the frozen identity authority"
                )
            semantic_fields = {
                "tenant_id",
                "dataset_id",
                "agent_id",
                "status",
                "jurisdiction",
                "is_current",
                "valid_from",
                "valid_to",
            }
            for field_name in semantic_fields.intersection(record):
                if not any(
                    getattr(row, field_name) == record[field_name] for row in bound_rows
                ):
                    raise _scope_fixture_error(
                        f"fixture {fixture_id!r} {field_name} metadata differs from the frozen identity authority"
                    )

            if (
                case_id == "cross_tenant_search"
                and record.get("tenant_id") != forbidden_tenant
            ):
                raise _scope_fixture_error(
                    f"cross-tenant fixture {fixture_id!r} does not belong to forbidden tenant"
                )
            if (
                case_id == "cross_dataset_search"
                and record.get("dataset_id") != forbidden_dataset
            ):
                raise _scope_fixture_error(
                    f"cross-dataset fixture {fixture_id!r} does not belong to forbidden dataset"
                )
            if (
                case_id == "cross_agent_search"
                and record.get("agent_id") != forbidden_agent
            ):
                raise _scope_fixture_error(
                    f"cross-agent fixture {fixture_id!r} does not belong to forbidden agent"
                )
            if case_id == "inactive_status_search" and str(
                record.get("status", "")
            ).upper() not in {"INACTIVE", "TOMBSTONED", "DELETED"}:
                raise _scope_fixture_error(
                    f"inactive fixture {fixture_id!r} is not inactive/tombstoned"
                )
            if case_id == "wrong_jurisdiction_search" and record.get(
                "jurisdiction"
            ) in {None, "TR"}:
                raise _scope_fixture_error(
                    f"wrong-jurisdiction fixture {fixture_id!r} is not outside TR"
                )
            if (
                case_id == "stale_version_search"
                and record.get("is_current") is not False
            ):
                raise _scope_fixture_error(
                    f"stale fixture {fixture_id!r} is not marked non-current"
                )
            if case_id == "effective_date_boundary_search":
                try:
                    valid_from = datetime.fromisoformat(
                        str(record["valid_from"]).replace("Z", "+00:00")
                    )
                    valid_to = datetime.fromisoformat(
                        str(record["valid_to"]).replace("Z", "+00:00")
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise _scope_fixture_error(
                        f"temporal fixture {fixture_id!r} lacks valid frozen effective dates"
                    ) from exc
                if valid_from <= probe_time <= valid_to:
                    raise _scope_fixture_error(
                        f"temporal fixture {fixture_id!r} is valid at the Phase 7 boundary"
                    )
            if (
                case_id.endswith("_visibility")
                and record.get("tenant_id") != forbidden_tenant
            ):
                raise _scope_fixture_error(
                    f"visibility fixture {fixture_id!r} does not belong to forbidden tenant"
                )

    scope = QualificationScope(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        dataset_ids=list(dataset_ids),
        agent_id=agent_id,
        expected_principal=expected_principal,
    )
    test_authority = ScopeTestAuthority(
        forbidden_tenant=forbidden_tenant,
        forbidden_dataset=forbidden_dataset,
        forbidden_agent=forbidden_agent,
        authorized_document=authorized_document,
        case_evidence_fixtures=normalized_case_fixtures,
        fixture_authority_hash=hashlib.sha256(
            canonical_json_bytes(fixtures_dict)
        ).hexdigest(),
    )
    return scope, test_authority


def _validate_static_preconditions(config: QualificationConfig) -> None:
    if not config.run_id or not config.run_id.strip():
        raise QualificationRunnerError("run_id must be non-empty")
    if config.run_dir.name != config.run_id:
        raise QualificationRunnerError("run_dir basename must equal run_id")
    if not config.freeze_path.is_file():
        raise QualificationRunnerError(f"freeze_path missing: {config.freeze_path}")
    if not config.checksum_path.is_file():
        raise QualificationRunnerError(f"checksum_path missing: {config.checksum_path}")
    for repo_name in ("MESA", "MESA_Data", "MESA_E2E_Certification"):
        sha = config.current_repository_shas.get(repo_name)
        if not sha or len(sha) not in {40, 64}:
            raise QualificationRunnerError(
                f"unresolved repository identity for {repo_name}: {sha!r}"
            )
    if not config.sqlite_path.is_file():
        raise QualificationRunnerError(f"SQLite store not found: {config.sqlite_path}")
    if not config.lancedb_dir.is_dir():
        raise QualificationRunnerError(
            f"LanceDB directory not found: {config.lancedb_dir}"
        )
    if not config.kuzu_dir.is_dir():
        raise QualificationRunnerError(f"Kùzu directory not found: {config.kuzu_dir}")


def run_profile_b_qualification(config: QualificationConfig) -> QualificationResult:
    """Execute the sole official qualification path.

    This API intentionally accepts configuration only. Test callbacks and
    pre-created responses are not part of the production authority boundary.
    """

    _validate_static_preconditions(config)
    freeze_verification = verify_contract_freeze(
        config.freeze_path,
        config.checksum_path,
        repository_root=config.repository_root,
        current_repository_shas=config.current_repository_shas,
    )
    if freeze_verification.status is not FreezeStatus.PASS:
        raise QualificationRunnerError(
            f"Contract freeze verification failed: {freeze_verification.drift}"
        )
    freeze = _load_freeze(config.freeze_path, config.run_id)
    (
        authority,
        ground_truth,
        relational,
        identity_map,
    ) = _load_required_scoring_authority(config)
    scope, test_scope_authority = _load_frozen_scope_authority(freeze, identity_map)
    if config.qualification_scope is not None and config.qualification_scope != scope:
        raise QualificationRunnerError(
            "caller-provided qualification_scope contradicts frozen qualification authority"
        )
    transport = _trusted_transport_from_freeze(config, freeze)
    answer_transport = _trusted_answer_transport(config, freeze, authority)
    freeze_sha256 = hashlib.sha256(config.freeze_path.read_bytes()).hexdigest()
    execution_session = _begin_official_execution(
        run_id=config.run_id,
        run_dir=config.run_dir,
        freeze_sha256=freeze_sha256,
        mesa_sha=config.current_repository_shas["MESA"],
        transport=transport,
        answer_transport=answer_transport,
    )

    tx = CertificationTransaction(
        run_id=config.run_id,
        run_dir=config.run_dir,
        gate_config_path=config.gate_config_path,
        execution_session=execution_session,
    )
    try:
        tx.execute_bootstrap()
        tx.execute_freeze(
            config.freeze_path,
            config.checksum_path,
            repository_root=config.repository_root,
            current_repository_shas=config.current_repository_shas,
        )

        def _execute_production_workload(run_dir: Path) -> None:
            store = RunArtifactStore(
                run_dir,
                config.run_id,
                execution_session=execution_session,
            )
            mesa_sha = config.current_repository_shas["MESA"]

            # 1. Start native MESA session with frozen qualification scope
            session_start_request = {
                "tenant_id": scope.tenant_id,
                "workspace_id": scope.workspace_id,
                "dataset_ids": list(scope.dataset_ids),
                "agent_id": scope.agent_id,
            }
            session_receipt = transport.start_session(session_start_request)
            if not 200 <= session_receipt.status_code < 300:
                raise QualificationRunnerError(
                    f"native MESA session bootstrap returned HTTP {session_receipt.status_code}"
                )
            session_payload = session_receipt.payload
            native_session_id = session_payload.get("session_id")
            if not isinstance(native_session_id, str) or not native_session_id:
                raise QualificationRunnerError(
                    "native MESA session bootstrap response missing session_id"
                )

            # Validate scope fields against frozen qualification scope
            if session_payload.get("tenant_id") != scope.tenant_id:
                raise QualificationRunnerError(
                    f"session bootstrap tenant mismatch: {session_payload.get('tenant_id')} != {scope.tenant_id}"
                )
            if session_payload.get("workspace_id") != scope.workspace_id:
                raise QualificationRunnerError(
                    f"session bootstrap workspace mismatch: {session_payload.get('workspace_id')} != {scope.workspace_id}"
                )
            if sorted(session_payload.get("dataset_ids", [])) != sorted(
                scope.dataset_ids
            ):
                raise QualificationRunnerError(
                    f"session bootstrap datasets mismatch: {session_payload.get('dataset_ids')} != {scope.dataset_ids}"
                )
            if session_payload.get("agent_id") != scope.agent_id:
                raise QualificationRunnerError(
                    f"session bootstrap agent mismatch: {session_payload.get('agent_id')} != {scope.agent_id}"
                )
            if (
                "principal_id" in session_payload
                and session_payload.get("principal_id") != scope.expected_principal
            ):
                raise QualificationRunnerError(
                    f"session bootstrap principal mismatch: {session_payload.get('principal_id')} != {scope.expected_principal}"
                )

            # Persist and seal raw session bootstrap artifact
            session_bootstrap_path = store.persist_raw_session_bootstrap(
                purpose="qualification",
                request=session_start_request,
                response=session_payload,
                transport_status=session_receipt.status_code,
                timestamp_utc=datetime.now(timezone.utc),
                latency_ms=session_receipt.latency_ms,
                mesa_runtime_profile=config.mesa_runtime_profile,
                mesa_sha=mesa_sha,
                api_version=config.api_version,
                execution_id=execution_session.execution_id,
            )
            execution_session.register_transport_artifact(
                session_bootstrap_path,
                receipt=session_receipt,
                request=session_start_request,
                response=session_payload,
                collector="harness.qualification_runner.session_bootstrap",
            )

            primary_dataset = scope.dataset_ids[0]
            try:
                for item in ground_truth:
                    request = {
                        "session_id": native_session_id,
                        "dataset_ids": [primary_dataset],
                        "query": item.question,
                        "limit": 5,
                    }
                    receipt = transport.search(request)
                    raw_path = store.persist_raw_retrieval(
                        query_id=item.query_id,
                        request=request,
                        response=receipt.payload,
                        transport_status=receipt.status_code,
                        timestamp_utc=datetime.now(timezone.utc),
                        latency_ms=receipt.latency_ms,
                        runtime_lock_sha256=freeze_sha256,
                        execution_id=execution_session.execution_id,
                    )
                    execution_session.register_transport_artifact(
                        raw_path,
                        receipt=receipt,
                        request=request,
                        response=receipt.payload,
                        collector="harness.qualification_runner.retrieval",
                    )
                    context_request = {
                        "query": item.question,
                        "token_budget": 2048,
                    }
                    context_receipt = transport.call_endpoint(
                        f"GET /v4/sessions/{native_session_id}/context",
                        context_request,
                    )
                    context_path = store.persist_raw_context(
                        query_id=item.query_id,
                        request=context_request,
                        response=context_receipt.payload,
                        transport_status=context_receipt.status_code,
                        timestamp_utc=datetime.now(timezone.utc),
                        latency_ms=context_receipt.latency_ms,
                        execution_id=execution_session.execution_id,
                    )
                    execution_session.register_transport_artifact(
                        context_path,
                        receipt=context_receipt,
                        request=context_request,
                        response=context_receipt.payload,
                        collector="harness.qualification_runner.context",
                    )
                    context_capture = normalize_context_response(
                        run_id=config.run_id,
                        query_id=item.query_id,
                        response=context_receipt.payload,
                        api_version=config.api_version,
                        mesa_sha=mesa_sha,
                    )
                    execute_answer_and_persist(
                        store=store,
                        context=context_capture,
                        question=item.question,
                        system_prompt=config.answer_system_prompt,
                        answer_instruction=config.answer_instruction,
                        model=authority.answer_model,
                        request_parameters=config.answer_request_parameters,
                        transport=answer_transport,
                        execution_session=execution_session,
                        context_raw_path=context_path,
                    )

                def _scope_executor(case: ScopeTestCase):
                    return transport.call_endpoint(case.endpoint, case.request_payload)

                phase7_cases = build_canonical_scope_test_matrix(
                    authorized_tenant=scope.tenant_id,
                    authorized_workspace=scope.workspace_id,
                    authorized_dataset=primary_dataset,
                    authorized_agent=scope.agent_id,
                    authorized_principal=scope.expected_principal,
                    session_id=native_session_id,
                    forbidden_tenant=test_scope_authority.forbidden_tenant,
                    forbidden_dataset=test_scope_authority.forbidden_dataset,
                    forbidden_agent=test_scope_authority.forbidden_agent,
                    authorized_document=test_scope_authority.authorized_document,
                    case_evidence_fixtures=test_scope_authority.case_evidence_fixtures,
                    fixture_authority_hash=test_scope_authority.fixture_authority_hash,
                )
                collect_phase7_scope_isolation(
                    run_id=config.run_id,
                    run_dir=run_dir,
                    mesa_sha=mesa_sha,
                    test_cases=phase7_cases,
                    mesa_executor=_scope_executor,
                    api_version=config.api_version,
                    execution_session=execution_session,
                    session_id=native_session_id,
                    fixture_authority_hash=test_scope_authority.fixture_authority_hash,
                )

                storage_root = config.mesa_storage_root or config.sqlite_path.parent
                with establish_paired_state_stability(
                    run_id=config.run_id,
                    sqlite_path=config.sqlite_path,
                    storage_root=storage_root,
                ) as state_stability_guard:
                    execute_paired_graph_ablation(
                        run_id=config.run_id,
                        run_dir=run_dir,
                        mesa_sha=mesa_sha,
                        rel_queries=relational,
                        identity_map=identity_map,
                        sqlite_path=config.sqlite_path,
                        lancedb_dir=config.lancedb_dir,
                        kuzu_dir=config.kuzu_dir,
                        mesa_executor=lambda _mode, request: transport.search(request),
                        state_stability_guard=state_stability_guard,
                        execution_session=execution_session,
                        api_version=config.api_version,
                        session_id=native_session_id,
                        dataset_ids=[primary_dataset],
                    )
            finally:
                try:
                    transport.end_session(native_session_id)
                except Exception:
                    pass

        tx.execute_raw_execution(_execute_production_workload)
        raw_manifest_hash = tx.execute_raw_sealing()
        tx.execute_oracle_audit()
        tx.execute_scoring()
        gate_results = tx.execute_gate_evaluation()
        final_verdict = tx.execute_verdict_derivation()
        release_path = None
        if config.release_root is not None:
            evidence_records = [
                {
                    "path": name,
                    "sha256": hashlib.sha256(
                        (config.run_dir / name).read_bytes()
                    ).hexdigest(),
                    "producer": "official_qualification_runner",
                    "phase": "qualification",
                    "timestamp_utc": datetime.now(timezone.utc),
                    "source_run_id": config.run_id,
                    "immutable": True,
                    "sealed": True,
                    "artifact_type": "evidence",
                }
                for name in [
                    "official-execution.json",
                    "raw-manifest.json",
                    "scope-isolation.json",
                    "graph-ablation.json",
                    "verdict.json",
                ]
                if (config.run_dir / name).is_file()
            ]
            tx.execute_evidence_index(evidence_records)
            tx.execute_run_id_consistency()
            tx.execute_health_verification()
            release_result = tx.execute_release_finalization(config.release_root)
            release_path = Path(str(release_result["release_dir"]))
    except (TransactionError, StateProofError) as exc:
        raise QualificationRunnerError(str(exc)) from exc

    return QualificationResult(
        run_id=config.run_id,
        final_verdict=final_verdict.status.value,
        status="COMPLETED" if not tx.failed else "FAILED",
        raw_manifest_hash=raw_manifest_hash,
        release_path=release_path,
        gate_results=[gate.model_dump(mode="json") for gate in gate_results],
        failure_reason=tx.failure_reason,
    )
