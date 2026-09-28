"""Tests for frozen multi-store state proof, paired graph ablation, and B11."""

from __future__ import annotations

import fcntl
import json
import sqlite3
from pathlib import Path

import pytest

from harness.identity import IdentityMap
from harness.mesa_adapters import MESAContractIntegrityError
from harness.metric_producers import (
    ProducerContext,
    ProducerIntegrityError,
    _b11,
    write_sealed_measurement,
)
from harness.artifacts import RunArtifactStore
from harness.models import GroundTruthItem
from harness.graph_collector import execute_paired_graph_ablation
from harness.state_proof import (
    STATE_PROOF_CONTRACT_VERSION,
    StateProofError,
    acquire_runtime_quiescence,
    capture_frozen_state_proof,
    verify_store_quiescence,
)

RUN_ID = "RUN-graph-test"
MESA_SHA = "b" * 40


def _setup_mock_stores(tmp_path: Path) -> tuple[Path, Path, Path]:
    sql_path = tmp_path / "mesa.db"
    conn = sqlite3.connect(sql_path)
    conn.execute("CREATE TABLE assertions (id TEXT PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO assertions VALUES ('a1', 'legal text')")
    conn.execute("CREATE TABLE projection_outbox (state TEXT NOT NULL)")
    conn.execute("CREATE TABLE artifact_cleanup_outbox (state TEXT NOT NULL)")
    conn.execute("CREATE TABLE dispatch_queue (state TEXT NOT NULL)")
    conn.execute("CREATE TABLE lancedb_wal (state TEXT NOT NULL)")
    conn.execute("CREATE TABLE session_finalization_journal (state TEXT NOT NULL)")
    conn.execute("CREATE TABLE raw_logs (status TEXT NOT NULL)")
    conn.commit()
    conn.close()
    (tmp_path / ".mesa-single-writer.lock").write_text("owner=stopped\n")

    lance_dir = tmp_path / "lancedb_data"
    lance_dir.mkdir()
    (lance_dir / "table.lance").mkdir()
    (lance_dir / "table.lance" / "1.manifest").write_text("manifest-1")
    (lance_dir / "table.lance" / "data.lance").write_text("data-1")

    kuzu_dir = tmp_path / "kuzu_data"
    kuzu_dir.mkdir()
    (kuzu_dir / "catalog.kz").write_text("catalog-data")
    (kuzu_dir / "nodes.kz").write_text("nodes-data")
    (kuzu_dir / "edges.kz").write_text("edges-data")

    return sql_path, lance_dir, kuzu_dir


def _mock_rel_queries() -> list[GroundTruthItem]:
    from harness.models import EvidenceGroup, RequiredFact

    return [
        GroundTruthItem(
            query_id=f"REL-{i:02d}",
            question=f"What is rule {i}?",
            expected_source_chunk_ids=[f"src-rel-{i}"],
            evidence_groups=[
                EvidenceGroup(
                    group_id=f"grp-{i}",
                    acceptable_source_chunk_ids=[f"src-rel-{i}"],
                )
            ],
            required_facts=[RequiredFact(fact_id=f"F{i}", claim=f"Fact {i}")],
            query_class="RELATIONAL",
            is_answerable=True,
        )
        for i in range(1, 11)
    ]


def _mock_identity_map() -> IdentityMap:
    id_map = IdentityMap()
    for i in range(1, 11):
        id_map.add_mapping(f"chunk-rel-{i}", f"src-rel-{i}")
        id_map.add_mapping(f"chunk-sup-{i}", f"src-sup-{i}")
        id_map.add_mapping(f"chunk-unrelated-{i}", f"src-unrelated-{i}")
    return id_map


def _mock_graph_executor(mode: str, req: dict) -> dict:
    q_id = req.get("query")
    num = 1
    for i in range(1, 11):
        if str(i) in q_id:
            num = i
            break

    enabled = mode == "enabled"
    ev_id = f"ev-rel-{num}"
    chunk_id = f"chunk-rel-{num}" if (enabled or num > 2) else f"chunk-unrelated-{num}"

    matched = {
        "assertion_id": ev_id,
        "tenant_id": "tenant-1",
        "dataset_id": "dataset-legal-1",
        "document_id": "doc-1",
        "revision_id": "rev-1",
        "chunk_id": chunk_id,
        "status": "ACTIVE",
        "jurisdiction": "TR",
        "valid_from": "2026-01-01",
        "valid_to": "",
        "evidence_span": f"Rule {num} definition",
    }

    support = []
    graph_paths = []
    origins = ["vector", "bm25"]
    if enabled:
        origins.append("graph")
        graph_paths.append(
            {
                "graph_path_id": f"sha256:path-{num}",
                "assertion_ids": [f"ev-sup-{num}", ev_id],
                "entity_ids": ["ent-1", "ent-2", "ent-3"],
                "edge_directions": ["forward", "reverse"],
                "predicates": ["governs", "cites"],
                "seed_id": "ent-1",
                "score": 0.85,
            }
        )
        support.append(
            {
                "assertion_id": f"ev-sup-{num}",
                "tenant_id": "tenant-1",
                "dataset_id": "dataset-legal-1",
                "document_id": "doc-1",
                "revision_id": "rev-1",
                "chunk_id": f"chunk-sup-{num}",
                "status": "ACTIVE",
                "jurisdiction": "TR",
                "valid_from": "2026-01-01",
                "valid_to": "",
                "evidence_span": "support span",
            }
        )

    res = {
        "candidate_id": ev_id,
        "evidence_id": ev_id,
        "assertion_id": ev_id,
        "source_chunk_id": chunk_id,
        "document_id": "doc-1",
        "evidence_span": f"Rule {num} definition",
        "raw_score": 0.9 if enabled else 0.4,
        "rrf_score": 0.05 if enabled else 0.02,
        "legal_factor": 1.0,
        "final_score": 0.05 if enabled else 0.02,
        "provenance": [matched, *support],
        "matched_assertions": [matched],
        "supporting_assertions": support,
        "retrieval_provenance": {
            "origins": origins,
            "graph_paths": graph_paths,
            "lane_ranks": {"graph": 1 if enabled else None},
        },
    }

    pair_id = f"sha256:pair-{num}"
    return {
        "session_id": req["session_id"],
        "dataset_ids": req["dataset_ids"],
        "results": [res],
        "graph_ablation": {
            "contract_version": "mesa.graph-ablation.v1",
            "mode": mode,
            "pair_identity": pair_id,
            "query_identity": f"query-rel-{num}",
            "retrieval_config_identity": "ret-cfg-1",
            "scope_identity": "scope-id-1",
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


def test_state_proof_quiescence_and_mutation_detection(tmp_path: Path) -> None:
    sql, lance, kuzu = _setup_mock_stores(tmp_path)

    pre = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    assert pre.contract_version == STATE_PROOF_CONTRACT_VERSION
    assert pre.sqlite_fingerprint.startswith("sha256:")
    assert pre.lancedb_fingerprint.startswith("sha256:")
    assert pre.kuzu_fingerprint.startswith("sha256:")

    # Read-only check without quiescence evidence: state unchanged, but quiescence NOT verified
    post = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, quiescent = verify_store_quiescence(pre, post)
    assert ok is True
    assert msg == "RETRIEVAL_STATE_UNCHANGED"
    assert quiescent is False

    # With the real MESA writer fence and drained durable queues: verified.
    with acquire_runtime_quiescence(run_id=RUN_ID, sqlite_path=sql) as lease:
        ok, msg, quiescent = verify_store_quiescence(pre, post, quiescence_lease=lease)
        assert ok is True
        assert quiescent is True

    # SQLite mutation
    conn = sqlite3.connect(sql)
    conn.execute("INSERT INTO assertions VALUES ('a2', 'mutation')")
    conn.commit()
    conn.close()

    post_mutated = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, _ = verify_store_quiescence(pre, post_mutated)
    assert ok is False
    assert "SQLite" in msg

    # LanceDB mutation
    (lance / "table.lance" / "2.manifest").write_text("manifest-2")
    post_lance = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, _ = verify_store_quiescence(pre, post_lance)
    assert ok is False
    assert "LanceDB" in msg or "SQLite" in msg

    # Kuzu mutation
    (kuzu / "edges.kz").write_text("edges-mutated")
    post_kuzu = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, _ = verify_store_quiescence(pre, post_kuzu)
    assert ok is False


def test_runtime_quiescence_rejects_active_mesa_writer(tmp_path: Path) -> None:
    sql, _lance, _kuzu = _setup_mock_stores(tmp_path)
    lock_path = tmp_path / ".mesa-single-writer.lock"

    with lock_path.open("r+", encoding="utf-8") as active_writer:
        fcntl.flock(active_writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(StateProofError, match="active writer"):
            acquire_runtime_quiescence(run_id=RUN_ID, sqlite_path=sql)


def test_runtime_quiescence_rejects_durable_worker_backlog(tmp_path: Path) -> None:
    sql, _lance, _kuzu = _setup_mock_stores(tmp_path)
    with sqlite3.connect(sql) as connection:
        connection.execute("INSERT INTO projection_outbox VALUES ('PENDING')")

    with pytest.raises(StateProofError, match="backlog has not drained"):
        acquire_runtime_quiescence(run_id=RUN_ID, sqlite_path=sql)


def test_paired_graph_ablation_end_to_end(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    queries = _mock_rel_queries()
    id_map = _mock_identity_map()

    with acquire_runtime_quiescence(run_id=RUN_ID, sqlite_path=sql) as lease:
        artifact_path = execute_paired_graph_ablation(
            run_id=RUN_ID,
            run_dir=run_dir,
            mesa_sha=MESA_SHA,
            rel_queries=queries,
            identity_map=id_map,
            sqlite_path=sql,
            lancedb_dir=lance,
            kuzu_dir=kuzu,
            mesa_executor=_mock_graph_executor,
            quiescence_lease=lease,
        )
    assert artifact_path.is_file()
    assert (run_dir / "graph-ablation.json.SHA256").is_file()

    ctx = _dummy_ctx(run_dir)
    obs = _b11(ctx)
    assert obs.execution == "COMPLETED"
    assert obs.observed["graph_capability_operational"] is True
    assert obs.observed["graph_causal_ablation_proven"] is True
    assert obs.observed["graph_rel_contribution_count"] >= 3


def test_regression_duplicate_path_scoped_to_pair(tmp_path: Path) -> None:
    """Ensure legitimate shared graph paths across queries do NOT fail B11,

    while duplicate path amplification inside a single query pair is rejected.
    """
    shared_path_id = "sha256:shared-valid-graph-path"

    # Pair 0 and Pair 1 both use the exact same shared path ID across separate queries
    def executor_with_shared_path(mode: str, req: dict) -> dict:
        resp = _mock_graph_executor(mode, req)
        if mode == "enabled" and resp.get("results"):
            resp["results"][0]["retrieval_provenance"]["graph_paths"][0][
                "graph_path_id"
            ] = shared_path_id
        return resp

    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    queries = _mock_rel_queries()
    id_map = _mock_identity_map()

    # Shared path across separate queries should succeed without error!
    with acquire_runtime_quiescence(run_id=RUN_ID, sqlite_path=sql) as lease:
        execute_paired_graph_ablation(
            run_id=RUN_ID,
            run_dir=run_dir,
            mesa_sha=MESA_SHA,
            rel_queries=queries,
            identity_map=id_map,
            sqlite_path=sql,
            lancedb_dir=lance,
            kuzu_dir=kuzu,
            mesa_executor=executor_with_shared_path,
            quiescence_lease=lease,
        )

    ctx = _dummy_ctx(run_dir)
    obs = _b11(ctx)
    assert obs.execution == "COMPLETED"
    assert obs.observed["graph_capability_operational"] is True

    # Now test duplicate amplification within a single query: should fail!
    dup_dir = tmp_path / "dup_test"
    dup_dir.mkdir()

    def executor_with_duplicate_in_query(mode: str, req: dict) -> dict:
        resp = _mock_graph_executor(mode, req)
        if mode == "enabled" and resp.get("results"):
            path_copy = dict(
                resp["results"][0]["retrieval_provenance"]["graph_paths"][0]
            )
            resp["results"][0]["retrieval_provenance"]["graph_paths"].append(path_copy)
        return resp

    with acquire_runtime_quiescence(run_id=RUN_ID, sqlite_path=sql) as lease:
        with pytest.raises(MESAContractIntegrityError, match="duplicate graph path"):
            execute_paired_graph_ablation(
                run_id=RUN_ID,
                run_dir=dup_dir,
                mesa_sha=MESA_SHA,
                rel_queries=queries,
                identity_map=id_map,
                sqlite_path=sql,
                lancedb_dir=lance,
                kuzu_dir=kuzu,
                mesa_executor=executor_with_duplicate_in_query,
                quiescence_lease=lease,
            )


def test_b11_rejects_missing_or_unverified_state_proof(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    queries = _mock_rel_queries()
    id_map = _mock_identity_map()

    execute_paired_graph_ablation(
        run_id=RUN_ID,
        run_dir=run_dir,
        mesa_sha=MESA_SHA,
        rel_queries=queries,
        identity_map=id_map,
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
        mesa_executor=_mock_graph_executor,
        quiescence_lease=None,  # No runner-owned quiescence lease
    )

    ctx = _dummy_ctx(run_dir)
    # 1. Sealed state proof lacked quiescence -> BLOCKED
    obs = _b11(ctx)
    assert obs.execution == "BLOCKED"
    assert "BLOCKED_BY_RUNTIME_STATE_PROOF" in obs.reason

    # 2. Caller claims quiescence_verified=True when sealed state proof does not verify it -> ProducerIntegrityError
    path = run_dir / "graph-ablation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["frozen_state_proof"]["quiescence_verified"] = True
    path.unlink()
    path.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(path, payload)

    with pytest.raises(
        ProducerIntegrityError, match="claimed quiescence_verified=True"
    ):
        _b11(ctx)


def test_b11_rejects_forged_producer(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    queries = _mock_rel_queries()
    id_map = _mock_identity_map()

    with acquire_runtime_quiescence(run_id=RUN_ID, sqlite_path=sql) as lease:
        execute_paired_graph_ablation(
            run_id=RUN_ID,
            run_dir=run_dir,
            mesa_sha=MESA_SHA,
            rel_queries=queries,
            identity_map=id_map,
            sqlite_path=sql,
            lancedb_dir=lance,
            kuzu_dir=kuzu,
            mesa_executor=_mock_graph_executor,
            quiescence_lease=lease,
        )

    path = run_dir / "graph-ablation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["producer"] = "caller-forged-producer"
    path.unlink()
    path.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(path, payload)

    ctx = _dummy_ctx(run_dir)
    with pytest.raises(ProducerIntegrityError, match="producer lineage"):
        _b11(ctx)
