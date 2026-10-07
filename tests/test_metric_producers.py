"""Adversarial tests for authoritative B0-B14 metric producers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from harness.gates import PRODUCTION_METRIC_PRODUCERS as REGISTERED_GATE_IDS
from harness.metric_producers import (
    PRODUCTION_GATE_IDS,
    PRODUCTION_METRIC_PRODUCERS,
    ProducerContext,
    ProducerIntegrityError,
    produce_all,
    write_sealed_measurement,
)
from harness.operations import (
    HealthPhase,
    HealthSnapshot,
    OperationalStatus,
    ResourceSample,
    ServiceHealth,
    write_health_snapshot,
    write_resource_artifacts,
)


RUN_ID = "RUN-20260927T120000Z-producers"
RAW_HASH = "a" * 64
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _ctx(tmp_path: Path) -> ProducerContext:
    import hashlib

    entries = []
    raw_dir = tmp_path / "raw"
    if raw_dir.is_dir():
        for file in sorted(raw_dir.rglob("*.json")):
            rel_path = file.relative_to(tmp_path).as_posix()
            entries.append(
                {
                    "path": rel_path,
                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                    "size_bytes": file.stat().st_size,
                }
            )
    manifest_bytes = (json.dumps(entries, sort_keys=True) + "\n").encode("utf-8")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "manifest_hash": manifest_hash,
        "entries": entries,
    }
    p = tmp_path / "raw-manifest.json"
    p_bytes = (json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    p.write_bytes(p_bytes)
    p_sha = hashlib.sha256(p_bytes).hexdigest()
    p.with_suffix(p.suffix + ".SHA256").write_text(
        f"{p_sha}  {p.name}\n", encoding="utf-8"
    )

    summary_path = tmp_path / "scoring-summary.json"
    if summary_path.is_file():
        s_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        s_payload["raw_manifest_hash"] = manifest_hash
        s_bytes = (json.dumps(s_payload, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        summary_path.write_bytes(s_bytes)
        s_sha = hashlib.sha256(s_bytes).hexdigest()
        summary_path.with_suffix(summary_path.suffix + ".SHA256").write_text(
            f"{s_sha}  {summary_path.name}\n", encoding="utf-8"
        )

    return ProducerContext(
        run_dir=tmp_path,
        run_id=RUN_ID,
        freeze_path=tmp_path / "contract-freeze.json",
        checksum_path=tmp_path / "contract-freeze.SHA256",
        repository_root=tmp_path,
        current_repository_shas={},
        raw_manifest_hash=manifest_hash,
        gate_config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "profile-b-gates.json",
    )


def _sealed(tmp_path: Path, name: str, payload: dict) -> Path:
    import hashlib

    if name == "graph-ablation.json":
        raw_state_dir = tmp_path / "raw" / "state"
        raw_state_dir.mkdir(parents=True, exist_ok=True)
        state_file = raw_state_dir / "state-proof.json"
        state_payload = {
            "schema_version": "1.0",
            "run_id": RUN_ID,
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

        payload["state_proof_artifact"] = "raw/state/state-proof.json"
        payload["state_proof_sha256"] = state_sha
        payload.setdefault("frozen_state_proof", {})[
            "state_proof_artifact"
        ] = "raw/state/state-proof.json"
        payload["frozen_state_proof"]["state_proof_sha256"] = state_sha
        payload["frozen_state_proof"]["retrieval_state_unchanged"] = True
        payload["frozen_state_proof"]["proof_mode"] = "stable_state_pair"
        payload["frozen_state_proof"]["pair_state_stability_verified"] = True
        payload["frozen_state_proof"]["runtime_quiescence_verified"] = False
        payload["frozen_state_proof"]["quiescence_verified"] = False

        raw_graph_dir = tmp_path / "raw" / "graph"
        raw_graph_dir.mkdir(parents=True, exist_ok=True)
        for pair in payload.get("pairs", []):
            qid = pair.get("on", {}).get("query_id") or "q"
            pair.setdefault("pair_identity", f"pair-{qid}")
            pair.setdefault("scope_identity", {"tenant_id": "t1", "agent_id": "a1"})

            on_side = pair.get("on", {})
            on_side.setdefault("pair_identity", pair["pair_identity"])
            on_side.setdefault("scope_identity", pair["scope_identity"])
            on_file = raw_graph_dir / f"{qid}_on.json"
            on_payload = {
                "schema_version": "1.0",
                "run_id": RUN_ID,
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
            pair["on_raw_artifact"] = f"raw/graph/{qid}_on.json"
            pair["on_raw_sha256"] = on_sha
            on_side["on_raw_artifact"] = f"raw/graph/{qid}_on.json"
            on_side["on_raw_sha256"] = on_sha

            off_side = pair.get("off", {})
            off_side.setdefault("pair_identity", pair["pair_identity"])
            off_side.setdefault("scope_identity", pair["scope_identity"])
            off_file = raw_graph_dir / f"{qid}_off.json"
            off_payload = {
                "schema_version": "1.0",
                "run_id": RUN_ID,
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
            pair["off_raw_artifact"] = f"raw/graph/{qid}_off.json"
            pair["off_raw_sha256"] = off_sha
            off_side["off_raw_artifact"] = f"raw/graph/{qid}_off.json"
            off_side["off_raw_sha256"] = off_sha

    return write_sealed_measurement(
        tmp_path / name,
        {"schema_version": "2.0", "run_id": RUN_ID, **payload},
    )


def _score(tmp_path: Path) -> None:
    _sealed(
        tmp_path,
        "scoring-summary.json",
        {
            "raw_manifest_hash": RAW_HASH,
            "scorer_version": "profile-b-official-v2",
            "lane_status": {"retrieval": "PASS", "answers": "PASS"},
            "metrics": {
                "answerable_mrr": 0.9,
                "answerable_recall_at_5": 0.9,
                "rel_complete_evidence_at_5": 0.8,
                "single_hop_recall_at_5": 0.95,
                "answerable_pass_rate": 0.9,
                "no_answer_pass_rate": 0.9,
                "unsupported_material_claim_rate": 0.0,
                "fabricated_evidence_chunk_ids": 0,
                "retrieval_population": 80,
                "answerable_population": 70,
                "single_hop_population": 60,
                "rel_population": 10,
                "answer_population": 80,
                "answerable_answer_population": 70,
                "no_answer_population": 10,
            },
        },
    )


def _scope(tmp_path: Path, *, capabilities: bool, forbidden: list[str]) -> None:
    import hashlib

    raw_dir = tmp_path / "raw" / "scope"
    raw_dir.mkdir(parents=True, exist_ok=True)
    case_ids = [
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
    for index, case_id in enumerate(case_ids):
        is_search = "search" in case_id
        raw_file = raw_dir / f"{case_id}.json"
        raw_payload = {"schema_version": "1.0", "run_id": RUN_ID, "case_id": case_id}
        raw_bytes = (json.dumps(raw_payload, sort_keys=True) + "\n").encode("utf-8")
        raw_file.write_bytes(raw_bytes)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        raw_file.with_suffix(raw_file.suffix + ".SHA256").write_text(
            f"{raw_sha}  {raw_file.name}\n"
        )

        cases.append(
            {
                "case_id": case_id,
                "proof_type": "search_pre_rank_scope"
                if is_search
                else "endpoint_visibility",
                "source_raw_artifact": f"raw/scope/{case_id}.json",
                "source_raw_sha256": raw_sha,
                "returned_forbidden_evidence_ids": (forbidden if index == 0 else []),
                "pre_rank_audit_verified": True
                if (is_search and capabilities)
                else False,
                "endpoint_visibility_verified": True if not is_search else False,
                "exclusion_audit_hash": f"sha256:{'0' * 64}"
                if (is_search and capabilities)
                else None,
                "evaluated_candidate_count": 10
                if (is_search and capabilities)
                else None,
                "excluded_candidate_count": 5 if (is_search and capabilities) else None,
                "eligible_candidate_count": 5 if (is_search and capabilities) else None,
            }
        )

    _sealed(
        tmp_path,
        "scope-isolation.json",
        {
            "schema_version": "2.0",
            "run_id": RUN_ID,
            "contract_version": "mesa.scope-audit.v1",
            "producer": "harness.scope_collector.collect_phase7_scope_isolation",
            "mesa_contract_capabilities": {
                "candidate_scope_identity": capabilities,
                "pre_rank_exclusion_audit": capabilities,
            },
            "negative_cases": cases,
        },
    )


def _graph_side(
    query_id: str,
    *,
    enabled: bool,
    coverage: float,
    rank: int | None,
    settings: str = "b" * 64,
) -> dict:
    return {
        "query_id": query_id,
        "dataset_id": "dataset-1",
        "mesa_sha": "c" * 40,
        "settings_sha256": settings,
        "graph_enabled": enabled,
        "graph_backend_status": (
            "OPERATIONAL" if enabled else "DISABLED_BY_NATIVE_SWITCH"
        ),
        "graph_backend_error": None,
        "top5_origins": [["graph"]] if enabled else [["vector"]],
        "paths": (
            [{"graph_path_id": f"path-{query_id}", "path_valid": True}]
            if enabled
            else []
        ),
        "complete_evidence_at_5": coverage,
        "first_relevant_rank": rank,
    }


def test_registry_contains_exactly_b0_through_b14() -> None:
    assert set(PRODUCTION_METRIC_PRODUCERS) == PRODUCTION_GATE_IDS
    assert REGISTERED_GATE_IDS == PRODUCTION_GATE_IDS


def test_missing_artifacts_never_produce_completed_or_pass_metrics(
    tmp_path: Path,
) -> None:
    observations = produce_all(_ctx(tmp_path))
    assert set(observations) == PRODUCTION_GATE_IDS
    assert all(item.execution == "BLOCKED" for item in observations.values())
    assert all(item.observed == {} for item in observations.values())
    assert all(
        "producer code is not frozen" in item.reason for item in observations.values()
    )


def test_b10_does_not_invent_zero_tenant_leakage(tmp_path: Path) -> None:
    _score(tmp_path)
    _scope(tmp_path, capabilities=False, forbidden=[])

    result = PRODUCTION_METRIC_PRODUCERS["B10"](_ctx(tmp_path))

    assert result.execution == "BLOCKED"
    assert result.observed == {}
    assert result.reason.startswith("BLOCKED_BY_MESA_CONTRACT:")


def test_b10_derives_nonzero_tenant_leakage_from_scope_artifact(tmp_path: Path) -> None:
    _score(tmp_path)
    _scope(tmp_path, capabilities=True, forbidden=["foreign-evidence"])

    result = PRODUCTION_METRIC_PRODUCERS["B10"](_ctx(tmp_path))

    assert result.execution == "COMPLETED"
    assert result.observed["tenant_leakage"] == 1


def test_b9_reports_verified_missing_mesa_contract(tmp_path: Path) -> None:
    _scope(tmp_path, capabilities=False, forbidden=[])

    result = PRODUCTION_METRIC_PRODUCERS["B9"](_ctx(tmp_path))

    assert result.execution == "BLOCKED"
    assert result.reason.startswith("BLOCKED_BY_MESA_CONTRACT:")


def test_b6_missing_retry_counts_cannot_pass_canary(tmp_path: Path) -> None:
    _sealed(
        tmp_path,
        "native-canary.json",
        {
            "publisher_component": "MESA_Data",
            "publish_route": "/v4/memory/insert",
            "diagnostic_bridge_used": False,
            "mutation_state": "COMMITTED",
            "source_chunk_id": "source-1",
            "search_source_chunk_id": "source-1",
        },
    )

    result = PRODUCTION_METRIC_PRODUCERS["B6"](_ctx(tmp_path))

    assert result.observed["canary_passed"] is False


def test_b6_hand_authored_committed_json_cannot_pass_official_mode(
    tmp_path: Path,
) -> None:
    path = _sealed(
        tmp_path,
        "native-canary.json",
        {
            "publisher_component": "MESA_Data",
            "publish_route": "/v4/memory/insert",
            "diagnostic_bridge_used": False,
            "mutation_state": "COMMITTED",
            "source_chunk_id": "source-1",
            "search_source_chunk_id": "source-1",
            "logical_count_before_retry": 1,
            "logical_count_after_retry": 1,
        },
    )

    class RejectingAuthority:
        def verify_derived_artifact(self, candidate: Path, artifact_type: str) -> None:
            assert candidate == path
            assert artifact_type == "native_canary"
            raise ValueError("not registered to this execution")

    official_ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=RejectingAuthority(),
    )
    with pytest.raises(ProducerIntegrityError, match="not runner-owned"):
        PRODUCTION_METRIC_PRODUCERS["B6"](official_ctx)


def test_b6_authoritative_interface_receipt_allows_recomputed_observation(
    tmp_path: Path,
) -> None:
    path = _sealed(
        tmp_path,
        "native-canary.json",
        {
            "publisher_component": "MESA_Data",
            "publish_route": "/v4/memory/insert",
            "diagnostic_bridge_used": False,
            "mutation_state": "COMMITTED",
            "source_chunk_id": "source-1",
            "search_source_chunk_id": "source-1",
            "logical_count_before_retry": 1,
            "logical_count_after_retry": 1,
        },
    )

    class FakeAuthoritativeInterface:
        def verify_derived_artifact(self, candidate: Path, artifact_type: str) -> None:
            assert candidate == path
            assert artifact_type == "native_canary"

    official_ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=FakeAuthoritativeInterface(),
    )
    result = PRODUCTION_METRIC_PRODUCERS["B6"](official_ctx)

    assert result.observed["canary_passed"] is True


def test_b7_duplicate_planned_chunk_is_not_a_complete_mapping(tmp_path: Path) -> None:
    _sealed(
        tmp_path,
        "delivery-evidence.json",
        {
            "planned_source_chunk_ids": ["source-1", "source-1"],
            "deliveries": [
                {
                    "source_chunk_id": "source-1",
                    "terminal_state": "COMMITTED",
                    "mesa_chunk_id": "mesa-1",
                    "mutation_id": "mutation-1",
                }
            ],
        },
    )

    with pytest.raises(ProducerIntegrityError, match="duplicates"):
        PRODUCTION_METRIC_PRODUCERS["B7"](_ctx(tmp_path))


@pytest.mark.parametrize(
    ("gate_id", "name", "artifact_type", "payload"),
    [
        (
            "B7",
            "delivery-evidence.json",
            "delivery_evidence",
            {
                "planned_source_chunk_ids": ["source-1"],
                "deliveries": [
                    {
                        "source_chunk_id": "source-1",
                        "terminal_state": "COMMITTED",
                        "mesa_chunk_id": "mesa-1",
                        "mutation_id": "mutation-1",
                    }
                ],
            },
        ),
        (
            "B8",
            "restart-idempotency.json",
            "restart_idempotency",
            {
                "before_restart_probe": {"fingerprint": "a" * 64},
                "after_restart_probe": {"fingerprint": "a" * 64},
                "restart_observed": True,
                "logical_count_before_republish": 1,
                "logical_count_after_republish": 1,
                "stable_idempotency_key": True,
                "republish_terminal_state": "ALREADY_COMMITTED",
            },
        ),
    ],
)
def test_upstream_claims_require_current_runner_authority(
    tmp_path: Path,
    gate_id: str,
    name: str,
    artifact_type: str,
    payload: dict,
) -> None:
    path = _sealed(tmp_path, name, payload)

    class StaleOrForeignAuthority:
        def verify_derived_artifact(self, candidate: Path, observed_type: str) -> None:
            assert candidate == path
            assert observed_type == artifact_type
            raise ValueError("artifact belongs to another run")

    official_ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=StaleOrForeignAuthority(),
    )
    with pytest.raises(ProducerIntegrityError, match="not runner-owned"):
        PRODUCTION_METRIC_PRODUCERS[gate_id](official_ctx)


def test_b8_missing_counts_and_empty_probes_cannot_pass(tmp_path: Path) -> None:
    _sealed(
        tmp_path,
        "restart-idempotency.json",
        {
            "before_restart_probe": {},
            "after_restart_probe": {},
            "restart_observed": True,
            "stable_idempotency_key": True,
            "republish_terminal_state": "COMMITTED",
        },
    )

    result = PRODUCTION_METRIC_PRODUCERS["B8"](_ctx(tmp_path))

    assert result.observed["restart_persistence_proven"] is False
    assert result.observed["idempotent_republish_proven"] is False


def test_b11_distinguishes_positive_neutral_and_harm(tmp_path: Path) -> None:
    pairs = [
        {
            "on": _graph_side("positive", enabled=True, coverage=1.0, rank=1),
            "off": _graph_side("positive", enabled=False, coverage=0.5, rank=4),
        },
        {
            "on": _graph_side("neutral", enabled=True, coverage=1.0, rank=2),
            "off": _graph_side("neutral", enabled=False, coverage=1.0, rank=2),
        },
        {
            "on": _graph_side("harm", enabled=True, coverage=0.5, rank=5),
            "off": _graph_side("harm", enabled=False, coverage=1.0, rank=1),
        },
    ]
    pairs.extend(
        {
            "on": _graph_side(f"neutral-{index}", enabled=True, coverage=1.0, rank=2),
            "off": _graph_side(f"neutral-{index}", enabled=False, coverage=1.0, rank=2),
        }
        for index in range(7)
    )
    _sealed(
        tmp_path,
        "graph-ablation.json",
        {
            "schema_version": "2.0",
            "run_id": RUN_ID,
            "contract_version": "mesa.graph-ablation.v1",
            "producer": "harness.graph_collector.execute_paired_graph_ablation",
            "mesa_contract_capabilities": {
                "stable_path_identity": True,
                "native_graph_on_off_switch": True,
            },
            "frozen_state_proof": {
                "state_proof_contract_version": "mesa.state-proof.v2",
                "pre_composite_fingerprint": "sha256:" + "0" * 64,
                "post_composite_fingerprint": "sha256:" + "0" * 64,
                "proof_mode": "stable_state_pair",
                "pair_state_stability_verified": True,
                "runtime_quiescence_verified": False,
            },
            "graph_capability_operational": True,
            "pairs": pairs,
        },
    )

    result = PRODUCTION_METRIC_PRODUCERS["B11"](_ctx(tmp_path))

    assert result.observed["graph_positive_utility_count"] == 1
    assert result.observed["graph_neutral_effect_count"] == 8
    assert result.observed["graph_harm_count"] == 1
    assert result.observed["graph_causal_ablation_proven"] is True


@pytest.mark.parametrize("mutation", ["query", "settings", "mode"])
def test_b11_rejects_unmatched_on_off_pair(tmp_path: Path, mutation: str) -> None:
    on = _graph_side("query-1", enabled=True, coverage=1.0, rank=1)
    off = _graph_side("query-1", enabled=False, coverage=0.5, rank=3)
    if mutation == "query":
        off["query_id"] = "query-2"
    elif mutation == "settings":
        off["settings_sha256"] = "d" * 64
    else:
        off["graph_enabled"] = True
    _sealed(
        tmp_path,
        "graph-ablation.json",
        {
            "schema_version": "2.0",
            "run_id": RUN_ID,
            "contract_version": "mesa.graph-ablation.v1",
            "producer": "harness.graph_collector.execute_paired_graph_ablation",
            "mesa_contract_capabilities": {
                "stable_path_identity": True,
                "native_graph_on_off_switch": True,
            },
            "frozen_state_proof": {
                "state_proof_contract_version": "mesa.state-proof.v2",
                "pre_composite_fingerprint": "sha256:" + "0" * 64,
                "post_composite_fingerprint": "sha256:" + "0" * 64,
                "proof_mode": "stable_state_pair",
                "pair_state_stability_verified": True,
                "runtime_quiescence_verified": False,
            },
            "graph_capability_operational": True,
            "pairs": [
                {"on": on, "off": off},
                *[
                    {
                        "on": _graph_side(
                            f"filler-{index}", enabled=True, coverage=1.0, rank=2
                        ),
                        "off": _graph_side(
                            f"filler-{index}", enabled=False, coverage=1.0, rank=2
                        ),
                    }
                    for index in range(9)
                ],
            ],
        },
    )

    with pytest.raises(ProducerIntegrityError, match="unmatched"):
        PRODUCTION_METRIC_PRODUCERS["B11"](_ctx(tmp_path))


def test_b11_logging_only_claim_cannot_prove_graph(tmp_path: Path) -> None:
    on = _graph_side("query-1", enabled=True, coverage=1.0, rank=1)
    off = _graph_side("query-1", enabled=False, coverage=1.0, rank=1)
    on["paths"] = []
    _sealed(
        tmp_path,
        "graph-ablation.json",
        {
            "schema_version": "2.0",
            "run_id": RUN_ID,
            "contract_version": "mesa.graph-ablation.v1",
            "producer": "harness.graph_collector.execute_paired_graph_ablation",
            "mesa_contract_capabilities": {
                "stable_path_identity": True,
                "native_graph_on_off_switch": True,
            },
            "frozen_state_proof": {
                "state_proof_contract_version": "mesa.state-proof.v2",
                "pre_composite_fingerprint": "sha256:" + "0" * 64,
                "post_composite_fingerprint": "sha256:" + "0" * 64,
                "proof_mode": "stable_state_pair",
                "pair_state_stability_verified": True,
                "runtime_quiescence_verified": False,
            },
            "graph_capability_operational": True,
            "pairs": [
                {"on": on, "off": off},
                *[
                    {
                        "on": _graph_side(
                            f"filler-{index}", enabled=True, coverage=1.0, rank=2
                        ),
                        "off": _graph_side(
                            f"filler-{index}", enabled=False, coverage=1.0, rank=2
                        ),
                    }
                    for index in range(9)
                ],
            ],
        },
    )

    result = PRODUCTION_METRIC_PRODUCERS["B11"](_ctx(tmp_path))

    assert result.observed["graph_provenance_verified"] is False
    assert result.observed["graph_causal_ablation_proven"] is False


def test_b13_recomputes_health_and_oom_instead_of_trusting_pass(tmp_path: Path) -> None:
    for name, phase in (
        ("health-pre-test.json", HealthPhase.PRE_TEST),
        ("health-post-test.json", HealthPhase.POST_TEST),
    ):
        write_health_snapshot(
            HealthSnapshot(
                run_id=RUN_ID,
                phase=phase,
                timestamp_utc=NOW,
                status=OperationalStatus.PASS,
                provider_reachable=True,
                services=[
                    ServiceHealth(
                        name="mesa", status=OperationalStatus.PASS, restarts=0
                    )
                ],
                host_metrics={"ram_mb": 1024},
                reasons=["serialized pass claim"],
            ),
            tmp_path / name,
        )
    sample = ResourceSample(
        run_id=RUN_ID,
        timestamp_utc=NOW,
        host_available_ram_mb=1024,
        mesa_rss_mb=512,
        swap_used_mb=0,
        disk_used_mb=100,
        provider_requests=1,
        provider_retries=0,
        provider_timeouts=0,
        container_restart_count=0,
        oom_killed_count=1,
        provider_expected_requests=1,
    )
    write_resource_artifacts([sample], [], tmp_path)

    result = PRODUCTION_METRIC_PRODUCERS["B13"](_ctx(tmp_path))

    assert result.observed["catastrophic_resource_failure"] == 1
    assert result.observed["oom_killed_count"] == 1


def test_measurement_seal_tamper_is_rejected(tmp_path: Path) -> None:
    _scope(tmp_path, capabilities=True, forbidden=[])
    path = tmp_path / "scope-isolation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["negative_cases"][0]["returned_forbidden_evidence_ids"] = ["hidden"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProducerIntegrityError, match="seal mismatch"):
        PRODUCTION_METRIC_PRODUCERS["B9"](_ctx(tmp_path))
