"""Tests for frozen multi-store state proof, paired graph ablation, and B11."""

from __future__ import annotations

import fcntl
import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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
    capture_frozen_state_proof,
    establish_paired_state_stability,
    verify_store_stability,
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
    conn.execute("CREATE TABLE memory_mutations (mutation_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE pipeline_run_events (event_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE projection_attempts (attempt_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE dispatch_receipts (receipt_id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE dispatch_completion_receipts (receipt_id TEXT PRIMARY KEY)"
    )
    conn.execute("CREATE TABLE v4_idempotency_receipts (receipt_id TEXT PRIMARY KEY)")
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


@contextmanager
def _combined_runtime_writer(storage_root: Path) -> Iterator[subprocess.Popen[str]]:
    """Hold the simulated MESA lifetime writer lock in a separate process."""

    script = """
import fcntl
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
handle = path.open("w+", encoding="utf-8")
fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
handle.write(f"owner=combined-runtime\\npid={os.getpid()}\\n")
handle.flush()
os.fsync(handle.fileno())
print("READY", flush=True)
sys.stdin.read(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(storage_root / ".mesa-single-writer.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    ready = process.stdout.readline().strip()
    if ready != "READY":
        stderr = process.stderr.read() if process.stderr is not None else ""
        process.kill()
        raise AssertionError(f"simulated combined runtime failed: {stderr}")
    try:
        yield process
    finally:
        if process.stdin is not None:
            process.stdin.write("x")
            process.stdin.flush()
        process.communicate(timeout=5)


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


def test_state_proof_stability_and_mutation_detection(tmp_path: Path) -> None:
    sql, lance, kuzu = _setup_mock_stores(tmp_path)

    pre = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    assert pre.contract_version == STATE_PROOF_CONTRACT_VERSION
    assert pre.sqlite_fingerprint.startswith("sha256:")
    assert pre.lancedb_fingerprint.startswith("sha256:")
    assert pre.kuzu_fingerprint.startswith("sha256:")

    # Fingerprints alone show equality, but lack live-runtime pair authority.
    post = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, pair_stable = verify_store_stability(pre, post)
    assert ok is True
    assert msg == "RETRIEVAL_STATE_UNCHANGED"
    assert pair_stable is False

    # MESA keeps its real writer fence; E2E observes it and proves a stable pair.
    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
        guarded_pre = capture_frozen_state_proof(
            run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
        )
        guarded_post = capture_frozen_state_proof(
            run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
        )
        ok, msg, pair_stable = verify_store_stability(
            guarded_pre, guarded_post, state_guard=guard
        )
        assert ok is True
        assert pair_stable is True
        assert guard.evidence()["writer_lock_acquired_by_e2e"] is False
        assert guard.evidence()["runtime_quiescence_verified"] is False

    # SQLite mutation
    conn = sqlite3.connect(sql)
    conn.execute("INSERT INTO assertions VALUES ('a2', 'mutation')")
    conn.commit()
    conn.close()

    post_mutated = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, _ = verify_store_stability(pre, post_mutated)
    assert ok is False
    assert "SQLite" in msg

    # LanceDB mutation
    (lance / "table.lance" / "2.manifest").write_text("manifest-2")
    post_lance = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, _ = verify_store_stability(pre, post_lance)
    assert ok is False
    assert "LanceDB" in msg or "SQLite" in msg

    # Kuzu mutation
    (kuzu / "edges.kz").write_text("edges-mutated")
    post_kuzu = capture_frozen_state_proof(
        run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
    )
    ok, msg, _ = verify_store_stability(pre, post_kuzu)
    assert ok is False


def test_live_mesa_writer_lock_is_observed_not_acquired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sql, lance, kuzu = _setup_mock_stores(tmp_path)

    with _combined_runtime_writer(tmp_path):
        monkeypatch.setattr(
            fcntl,
            "flock",
            lambda *_args, **_kwargs: pytest.fail(
                "E2E attempted to acquire MESA's lifetime writer lock"
            ),
        )
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
        pre = capture_frozen_state_proof(
            run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
        )
        post = capture_frozen_state_proof(
            run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
        )
        unchanged, _reason, stable = verify_store_stability(
            pre, post, state_guard=guard
        )
        assert unchanged is True
        assert stable is True


def test_state_stability_rejects_durable_worker_backlog(tmp_path: Path) -> None:
    sql, _lance, _kuzu = _setup_mock_stores(tmp_path)
    with sqlite3.connect(sql) as connection:
        connection.execute("INSERT INTO projection_outbox VALUES ('PENDING')")

    with _combined_runtime_writer(tmp_path):
        with pytest.raises(StateProofError, match="backlog has not drained"):
            establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)


def test_state_stability_rejects_runtime_identity_change(tmp_path: Path) -> None:
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
        pre = capture_frozen_state_proof(
            run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
        )
        (tmp_path / ".mesa-single-writer.lock").write_text(
            "owner=combined-runtime\npid=99999999\n", encoding="utf-8"
        )
        post = capture_frozen_state_proof(
            run_id=RUN_ID, sqlite_path=sql, lancedb_dir=lance, kuzu_dir=kuzu
        )
        unchanged, reason, stable = verify_store_stability(pre, post, state_guard=guard)
        assert unchanged is False
        assert stable is False
        assert "runtime identity" in reason


def test_state_stability_rejects_monotonic_mutation_marker_change(
    tmp_path: Path,
) -> None:
    sql, _lance, _kuzu = _setup_mock_stores(tmp_path)
    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
        with sqlite3.connect(sql) as connection:
            connection.execute("INSERT INTO memory_mutations VALUES ('mutation-1')")
        assert guard.finalize(RUN_ID) is False


def test_paired_graph_ablation_end_to_end(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    queries = _mock_rel_queries()
    id_map = _mock_identity_map()

    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
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
            state_stability_guard=guard,
        )
    assert artifact_path.is_file()
    assert (run_dir / "graph-ablation.json.SHA256").is_file()

    ctx = _dummy_ctx(run_dir)
    obs = _b11(ctx)
    assert obs.execution == "COMPLETED"
    assert obs.observed["graph_capability_operational"] is True
    assert obs.observed["graph_causal_ablation_proven"] is True
    assert obs.observed["graph_rel_contribution_count"] >= 3


@pytest.mark.parametrize("store_name", ["sqlite", "lancedb", "kuzu"])
def test_graph_pair_rejects_store_mutation_between_on_and_off(
    tmp_path: Path, store_name: str
) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    mutated = False

    def mutating_executor(mode: str, request: dict) -> dict:
        nonlocal mutated
        if mode == "disabled" and not mutated:
            mutated = True
            if store_name == "sqlite":
                with sqlite3.connect(sql) as connection:
                    connection.execute(
                        "INSERT INTO assertions VALUES ('during-pair', 'mutation')"
                    )
            elif store_name == "lancedb":
                (lance / "table.lance" / "during-pair.manifest").write_text(
                    "mutation", encoding="utf-8"
                )
            else:
                (kuzu / "edges.kz").write_text("during-pair", encoding="utf-8")
        return _mock_graph_executor(mode, request)

    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
        with pytest.raises(RuntimeError, match="mutated during paired execution"):
            execute_paired_graph_ablation(
                run_id=RUN_ID,
                run_dir=run_dir,
                mesa_sha=MESA_SHA,
                rel_queries=_mock_rel_queries(),
                identity_map=_mock_identity_map(),
                sqlite_path=sql,
                lancedb_dir=lance,
                kuzu_dir=kuzu,
                mesa_executor=mutating_executor,
                state_stability_guard=guard,
            )


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
    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
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
            state_stability_guard=guard,
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

    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
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
                state_stability_guard=guard,
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
        state_stability_guard=None,
    )

    ctx = _dummy_ctx(run_dir)
    # 1. Sealed state proof lacked runner-owned pair stability -> BLOCKED
    obs = _b11(ctx)
    assert obs.execution == "BLOCKED"
    assert "BLOCKED_BY_RUNTIME_STATE_PROOF" in obs.reason

    # 2. Caller cannot turn the state proof into a quiescence claim.
    path = run_dir / "graph-ablation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["frozen_state_proof"]["quiescence_verified"] = True
    path.unlink()
    path.with_suffix(".json.SHA256").unlink()
    write_sealed_measurement(path, payload)

    with pytest.raises(
        ProducerIntegrityError, match="falsely claims runtime quiescence"
    ):
        _b11(ctx)


def test_b11_rejects_forged_producer(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    sql, lance, kuzu = _setup_mock_stores(tmp_path)
    queries = _mock_rel_queries()
    id_map = _mock_identity_map()

    with _combined_runtime_writer(tmp_path):
        guard = establish_paired_state_stability(run_id=RUN_ID, sqlite_path=sql)
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
            state_stability_guard=guard,
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
