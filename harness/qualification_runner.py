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
from harness.artifacts import RunArtifactStore
from harness.execution_provenance import _begin_official_execution
from harness.freeze import FreezeStatus, verify_contract_freeze
from harness.graph_collector import execute_paired_graph_ablation
from harness.gt_governance import load_ground_truth, validate_ground_truth
from harness.identity import IdentityMap
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
from harness.scope_collector import ScopeTestCase, collect_phase7_scope_isolation
from harness.state_proof import StateProofError, establish_paired_state_stability
from harness.transaction import CertificationTransaction, TransactionError


class QualificationRunnerError(RuntimeError):
    """Raised when official qualification cannot establish its authority chain."""


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

            for item in ground_truth:
                request = {
                    "session_id": f"session-{config.run_id}",
                    "dataset_ids": ["dataset-legal-1"],
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
                    f"GET /v4/sessions/{request['session_id']}/context",
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

            collect_phase7_scope_isolation(
                run_id=config.run_id,
                run_dir=run_dir,
                mesa_sha=mesa_sha,
                mesa_executor=_scope_executor,
                api_version=config.api_version,
                execution_session=execution_session,
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
                )

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
