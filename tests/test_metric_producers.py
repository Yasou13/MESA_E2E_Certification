"""Adversarial tests for authoritative B0-B14 metric producers."""

from __future__ import annotations

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
    return ProducerContext(
        run_dir=tmp_path,
        run_id=RUN_ID,
        freeze_path=tmp_path / "contract-freeze.json",
        checksum_path=tmp_path / "contract-freeze.SHA256",
        repository_root=tmp_path,
        current_repository_shas={},
        raw_manifest_hash=RAW_HASH,
        gate_config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "profile-b-gates.json",
    )


def _sealed(tmp_path: Path, name: str, payload: dict) -> Path:
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
            "negative_cases": [
                {
                    "case_id": case_id,
                    "returned_forbidden_evidence_ids": (
                        forbidden if index == 0 else []
                    ),
                    "pre_rank_audit_verified": True,
                    "exclusion_audit_hash": f"sha256:{'0' * 64}",
                    "evaluated_candidate_count": 10,
                    "excluded_candidate_count": 5,
                    "eligible_candidate_count": 5,
                }
                for index, case_id in enumerate(case_ids)
            ],
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
            "mesa_contract_capabilities": {
                "stable_path_identity": True,
                "native_graph_on_off_switch": True,
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
            "mesa_contract_capabilities": {
                "stable_path_identity": True,
                "native_graph_on_off_switch": True,
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
            "mesa_contract_capabilities": {
                "stable_path_identity": True,
                "native_graph_on_off_switch": True,
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
