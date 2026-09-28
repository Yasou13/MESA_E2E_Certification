"""Authoritative paired Graph ON/OFF execution and ablation collector.

Executes matched Graph ON and Graph OFF queries against MESA V4 under verified
frozen multi-store quiescence. Derives complete_evidence_at_5 and first_relevant_rank
strictly via the official retrieval scorer, enforcing stable graph path identity
and fail-closed behavior on store mutation or pair mismatch.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from harness.identity import IdentityMap
from harness.mesa_adapters import (
    MESAContractIntegrityError,
    normalize_search_response,
    require_phase8_9_graph_contract,
)
from harness.metric_producers import write_sealed_measurement
from harness.mesa_transport import TrustedMESAResponse
from harness.models import GroundTruthItem
from harness.retrieval_scorer import score_retrieval
from harness.state_proof import (
    RuntimeQuiescenceLease,
    capture_frozen_state_proof,
    verify_store_quiescence,
    write_sealed_state_proof,
)

if TYPE_CHECKING:
    from harness.execution_provenance import OfficialExecutionSession


GRAPH_ABLATION_PRODUCER = "harness.graph_collector.execute_paired_graph_ablation"
GRAPH_ABLATION_CONTRACT_VERSION = "mesa.graph-ablation.v1"


def execute_paired_graph_ablation(
    *,
    run_id: str,
    run_dir: Path | str,
    mesa_sha: str,
    rel_queries: list[GroundTruthItem],
    identity_map: IdentityMap,
    sqlite_path: Path | str,
    lancedb_dir: Path | str,
    kuzu_dir: Path | str,
    mesa_executor: Callable[
        [str, dict[str, Any]], dict[str, Any] | TrustedMESAResponse
    ],
    settings_sha256: str = "b" * 64,
    api_version: str = "v4",
    session_id: str = "session-graph-ablation",
    dataset_ids: list[str] | None = None,
    quiescence_lease: RuntimeQuiescenceLease | None = None,
    execution_session: "OfficialExecutionSession | None" = None,
) -> Path:
    """Execute matched Graph ON/OFF queries under frozen multi-store state proof."""

    run_path = Path(run_dir)
    if len(rel_queries) != 10:
        raise ValueError(
            f"B11 requires exactly 10 REL ground truth queries, got {len(rel_queries)}"
        )

    datasets = dataset_ids or ["dataset-legal-1"]

    raw_graph_dir = run_path / "raw" / "graph"
    raw_graph_dir.mkdir(parents=True, exist_ok=True)

    # 1. Capture initial pre-state proof across all stores
    pre_proof = capture_frozen_state_proof(
        run_id=run_id,
        sqlite_path=sqlite_path,
        lancedb_dir=lancedb_dir,
        kuzu_dir=kuzu_dir,
    )

    pairs_evidence: list[dict[str, Any]] = []
    positive_count = 0
    neutral_count = 0
    harm_count = 0
    contribution_count = 0
    for q_idx, gt_item in enumerate(rel_queries, start=1):
        q_id = gt_item.query_id

        # Graph ON request
        req_on = {
            "session_id": session_id,
            "dataset_ids": datasets,
            "query": gt_item.question,
            "limit": 5,
            "graph_mode": "enabled",
        }
        exchange_on = mesa_executor("enabled", req_on)
        receipt_on: TrustedMESAResponse | None = None
        if isinstance(exchange_on, TrustedMESAResponse):
            receipt_on = exchange_on
            raw_resp_on = exchange_on.payload
        else:
            raw_resp_on = exchange_on
        if execution_session is not None and receipt_on is None:
            raise RuntimeError(
                "official Graph ON execution requires a trusted MESA transport receipt"
            )
        if not isinstance(raw_resp_on, dict):
            raise MESAContractIntegrityError(
                f"ON response for {q_id} must be an object"
            )

        # Persist sealed raw ON artifact
        on_raw_file = raw_graph_dir / f"{q_id}_on.json"
        on_raw_payload = {
            "schema_version": "1.0",
            "run_id": run_id,
            "lane": "graph",
            "query_id": q_id,
            "mode": "enabled",
            "graph_enabled": True,
            "request": req_on,
            "response": raw_resp_on,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        if execution_session is not None:
            on_raw_payload["execution_id"] = execution_session.execution_id
        on_bytes = (
            json.dumps(
                on_raw_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        on_raw_file.write_bytes(on_bytes)
        on_file_sha = hashlib.sha256(on_bytes).hexdigest()
        on_raw_file.with_suffix(on_raw_file.suffix + ".SHA256").write_text(
            f"{on_file_sha}  {on_raw_file.name}\n", encoding="utf-8", newline="\n"
        )
        on_rel_path = f"raw/graph/{q_id}_on.json"
        if execution_session is not None and receipt_on is not None:
            execution_session.register_transport_artifact(
                on_raw_file,
                receipt=receipt_on,
                request=req_on,
                response=raw_resp_on,
                collector=GRAPH_ABLATION_PRODUCER,
            )

        cap_on = normalize_search_response(
            run_id=run_id,
            query_id=q_id,
            request=req_on,
            response=raw_resp_on,
            api_version=api_version,
            mesa_sha=mesa_sha,
        )
        require_phase8_9_graph_contract(cap_on)

        if cap_on.graph_ablation is None or cap_on.graph_ablation.mode != "enabled":
            raise MESAContractIntegrityError(
                f"query {q_id} ON response missing graph_ablation mode='enabled'"
            )

        # Graph OFF request
        req_off = {
            "session_id": session_id,
            "dataset_ids": datasets,
            "query": gt_item.question,
            "limit": 5,
            "graph_mode": "disabled",
        }
        exchange_off = mesa_executor("disabled", req_off)
        receipt_off: TrustedMESAResponse | None = None
        if isinstance(exchange_off, TrustedMESAResponse):
            receipt_off = exchange_off
            raw_resp_off = exchange_off.payload
        else:
            raw_resp_off = exchange_off
        if execution_session is not None and receipt_off is None:
            raise RuntimeError(
                "official Graph OFF execution requires a trusted MESA transport receipt"
            )
        if not isinstance(raw_resp_off, dict):
            raise MESAContractIntegrityError(
                f"OFF response for {q_id} must be an object"
            )

        # Persist sealed raw OFF artifact
        off_raw_file = raw_graph_dir / f"{q_id}_off.json"
        off_raw_payload = {
            "schema_version": "1.0",
            "run_id": run_id,
            "lane": "graph",
            "query_id": q_id,
            "mode": "disabled",
            "graph_enabled": False,
            "request": req_off,
            "response": raw_resp_off,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        if execution_session is not None:
            off_raw_payload["execution_id"] = execution_session.execution_id
        off_bytes = (
            json.dumps(
                off_raw_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        off_raw_file.write_bytes(off_bytes)
        off_file_sha = hashlib.sha256(off_bytes).hexdigest()
        off_raw_file.with_suffix(off_raw_file.suffix + ".SHA256").write_text(
            f"{off_file_sha}  {off_raw_file.name}\n", encoding="utf-8", newline="\n"
        )
        off_rel_path = f"raw/graph/{q_id}_off.json"
        if execution_session is not None and receipt_off is not None:
            execution_session.register_transport_artifact(
                off_raw_file,
                receipt=receipt_off,
                request=req_off,
                response=raw_resp_off,
                collector=GRAPH_ABLATION_PRODUCER,
            )

        cap_off = normalize_search_response(
            run_id=run_id,
            query_id=q_id,
            request=req_off,
            response=raw_resp_off,
            api_version=api_version,
            mesa_sha=mesa_sha,
        )
        if cap_off.graph_ablation is None or cap_off.graph_ablation.mode != "disabled":
            raise MESAContractIntegrityError(
                f"query {q_id} OFF response missing graph_ablation mode='disabled'"
            )

        # Ensure OFF results have zero graph paths
        for res in cap_off.results:
            if res.graph_paths:
                raise MESAContractIntegrityError(
                    f"query {q_id} OFF results contain graph paths despite graph disabled"
                )

        # Pair identity verification
        if cap_on.graph_ablation.pair_identity != cap_off.graph_ablation.pair_identity:
            raise MESAContractIntegrityError(
                f"query {q_id} ON and OFF pair_identity mismatch: "
                f"{cap_on.graph_ablation.pair_identity} != {cap_off.graph_ablation.pair_identity}"
            )
        if (
            cap_on.graph_ablation.retrieval_config_identity
            != cap_off.graph_ablation.retrieval_config_identity
        ):
            raise MESAContractIntegrityError(
                f"query {q_id} retrieval_config_identity mismatch between ON and OFF"
            )

        # Official retrieval scoring on ON and OFF
        scorer_on = [
            {"rank": r.rank, "chunk_id": r.mesa_chunk_id, "score": r.final_score}
            for r in cap_on.results
        ]
        score_obj_on = score_retrieval(gt_item, scorer_on, identity_map)

        scorer_off = [
            {"rank": r.rank, "chunk_id": r.mesa_chunk_id, "score": r.final_score}
            for r in cap_off.results
        ]
        score_obj_off = score_retrieval(gt_item, scorer_off, identity_map)

        on_cov = score_obj_on.complete_evidence_at_5
        off_cov = score_obj_off.complete_evidence_at_5
        on_rank = score_obj_on.rank
        off_rank = score_obj_off.rank

        # Scoped duplicate path detection for this query/pair
        pair_paths: list[dict[str, Any]] = []
        pair_seen_path_ids: set[str] = set()
        for res in cap_on.results:
            for p in res.graph_paths:
                pid = p.stable_path_id
                if not pid:
                    raise MESAContractIntegrityError(
                        f"query {q_id} graph path missing stable_path_id"
                    )
                if pid in pair_seen_path_ids:
                    raise MESAContractIntegrityError(
                        f"duplicate graph path {pid} within query {q_id} cannot amplify contribution"
                    )
                pair_seen_path_ids.add(pid)
                pair_paths.append({"graph_path_id": pid, "path_valid": True})

        top5_origins = [
            list(r.debug_provenance.get("origins", [])) for r in cap_on.results[:5]
        ]
        has_graph_origin = any("graph" in origs for origs in top5_origins)
        if has_graph_origin and pair_paths:
            contribution_count += 1

        on_rank_key = on_rank if on_rank is not None else math.inf
        off_rank_key = off_rank if off_rank is not None else math.inf

        if on_cov > off_cov or (on_cov == off_cov and on_rank_key < off_rank_key):
            positive_count += 1
            outcome = "positive"
        elif on_cov < off_cov or (on_cov == off_cov and on_rank_key > off_rank_key):
            harm_count += 1
            outcome = "harm"
        else:
            neutral_count += 1
            outcome = "neutral"

        off_origins = [
            list(r.debug_provenance.get("origins", [])) for r in cap_off.results[:5]
        ]
        if any("graph" in origs for origs in off_origins):
            raise MESAContractIntegrityError(
                f"query {q_id} OFF results contain graph origin despite graph disabled"
            )

        pairs_evidence.append(
            {
                "query_id": q_id,
                "dataset_id": datasets[0],
                "pair_identity": cap_on.graph_ablation.pair_identity,
                "scope_identity": {
                    "tenant_id": (
                        cap_on.results[0].scope.tenant_id
                        if cap_on.results
                        else "default"
                    ),
                    "agent_id": (
                        cap_on.results[0].scope.agent_id
                        if cap_on.results
                        else "default"
                    ),
                },
                "on": {
                    "query_id": q_id,
                    "dataset_id": datasets[0],
                    "mesa_sha": mesa_sha,
                    "settings_sha256": settings_sha256,
                    "graph_enabled": True,
                    "graph_backend_status": "OPERATIONAL",
                    "complete_evidence_at_5": on_cov,
                    "first_relevant_rank": on_rank,
                    "top5_origins": top5_origins,
                    "paths": pair_paths,
                    "on_raw_artifact": on_rel_path,
                    "on_raw_sha256": on_file_sha,
                    "raw_response_sha256": cap_on.response_sha256,
                    "pair_identity": cap_on.graph_ablation.pair_identity,
                    "contract_version": cap_on.graph_ablation.contract_version,
                    "retrieval_config_identity": cap_on.graph_ablation.retrieval_config_identity,
                },
                "off": {
                    "query_id": q_id,
                    "dataset_id": datasets[0],
                    "mesa_sha": mesa_sha,
                    "settings_sha256": settings_sha256,
                    "graph_enabled": False,
                    "graph_backend_status": "DISABLED_BY_NATIVE_SWITCH",
                    "complete_evidence_at_5": off_cov,
                    "first_relevant_rank": off_rank,
                    "top5_origins": off_origins,
                    "paths": [],
                    "off_raw_artifact": off_rel_path,
                    "off_raw_sha256": off_file_sha,
                    "raw_response_sha256": cap_off.response_sha256,
                    "pair_identity": cap_off.graph_ablation.pair_identity,
                    "contract_version": cap_off.graph_ablation.contract_version,
                    "retrieval_config_identity": cap_off.graph_ablation.retrieval_config_identity,
                },
                "outcome": outcome,
            }
        )

    # 2. Capture post-state proof across all stores and verify unchanged state
    post_proof = capture_frozen_state_proof(
        run_id=run_id,
        sqlite_path=sqlite_path,
        lancedb_dir=lancedb_dir,
        kuzu_dir=kuzu_dir,
    )

    unchanged, reason, quiescent_verified = verify_store_quiescence(
        pre_proof, post_proof, quiescence_lease=quiescence_lease
    )
    if not unchanged:
        raise RuntimeError(reason)

    state_proof_path, state_proof_sha = write_sealed_state_proof(
        run_dir=run_path,
        run_id=run_id,
        pre_proof=pre_proof,
        post_proof=post_proof,
        store_locations={
            "sqlite": str(sqlite_path),
            "lancedb": str(lancedb_dir),
            "kuzu": str(kuzu_dir),
        },
        dataset_identity=datasets[0],
        quiescence_lease=quiescence_lease,
        execution_id=(
            execution_session.execution_id if execution_session is not None else None
        ),
    )
    if execution_session is not None:
        if quiescence_lease is None:
            raise RuntimeError(
                "official Graph execution requires runner-owned quiescence"
            )
        execution_session.register_state_artifact(
            state_proof_path,
            quiescence_lease=quiescence_lease,
            collector="harness.state_proof.write_sealed_state_proof",
        )

    payload = {
        "schema_version": "2.0",
        "run_id": run_id,
        "contract_version": GRAPH_ABLATION_CONTRACT_VERSION,
        "mesa_sha": mesa_sha,
        "producer": GRAPH_ABLATION_PRODUCER,
        "mesa_contract_capabilities": {
            "stable_path_identity": True,
            "native_graph_on_off_switch": True,
        },
        "graph_capability_operational": True,
        "state_proof_artifact": "raw/state/state-proof.json",
        "state_proof_sha256": state_proof_sha,
        "frozen_state_proof": {
            "state_proof_contract_version": pre_proof.contract_version,
            "pre_composite_fingerprint": pre_proof.composite_fingerprint,
            "post_composite_fingerprint": post_proof.composite_fingerprint,
            "sqlite_fingerprint": pre_proof.sqlite_fingerprint,
            "lancedb_fingerprint": pre_proof.lancedb_fingerprint,
            "kuzu_fingerprint": pre_proof.kuzu_fingerprint,
            "retrieval_state_unchanged": unchanged,
            "quiescence_verified": quiescent_verified,
        },
        "pairs": pairs_evidence,
    }
    if execution_session is not None:
        payload.update(execution_session.public_binding())

    target_path = run_path / "graph-ablation.json"
    write_sealed_measurement(target_path, payload)
    if execution_session is not None:
        execution_session.register_derived_artifact(
            target_path,
            artifact_type="graph_ablation",
            source_raw_paths=[
                "raw/state/state-proof.json",
                *[
                    side[key]
                    for pair in pairs_evidence
                    for side, key in (
                        (pair["on"], "on_raw_artifact"),
                        (pair["off"], "off_raw_artifact"),
                    )
                ],
            ],
        )
    return target_path
