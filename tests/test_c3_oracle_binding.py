from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.artifacts import (
    ArtifactOrderError,
    ImmutableArtifactError,
    RunArtifactStore,
)
from harness.oracle import audit_oracle_surfaces

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
RUN_ID = "RUN-20260924T120000Z-c3"


def _setup_clean_store(tmp_path: Path) -> RunArtifactStore:
    store = RunArtifactStore(tmp_path / RUN_ID, RUN_ID)
    store.initialize()
    store.persist_raw_retrieval(
        query_id="Q-1",
        request={"query": "clean query"},
        response={"results": [{"chunk_id": "M-1"}]},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=10.0,
        runtime_lock_sha256="a" * 64,
    )
    return store


def test_c3_audit_clean_raw_set_pass(tmp_path: Path) -> None:
    store = _setup_clean_store(tmp_path)
    raw_man = store.compute_raw_manifest()
    report = audit_oracle_surfaces(
        {"request": {"query": "clean query"}},
        raw_manifest=raw_man,
        run_id=RUN_ID,
    )
    store.persist_oracle_audit(report)
    scored = store.persist_scored(lane="retrieval", query_id="Q-1", score={"status": "HIT"})
    assert scored.is_file()


def test_c3_add_leaking_raw_request_after_audit_blocks_scoring(tmp_path: Path) -> None:
    store = _setup_clean_store(tmp_path)
    report = audit_oracle_surfaces({"request": {"query": "clean query"}})
    store.persist_oracle_audit(report)

    # Add a leaking raw request after audit
    store.persist_raw_retrieval(
        query_id="Q-2",
        request={"query": "leak", "gold_evidence_ids": ["G-1"]},
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=5.0,
        runtime_lock_sha256="a" * 64,
    )

    with pytest.raises(ArtifactOrderError, match="ORACLE_AUDIT_STALE|stale|mismatch"):
        store.persist_scored(lane="retrieval", query_id="Q-1", score={"status": "HIT"})


def test_c3_modify_audited_raw_file_blocked(tmp_path: Path) -> None:
    store = _setup_clean_store(tmp_path)
    report = audit_oracle_surfaces({"request": {"query": "clean query"}})
    store.persist_oracle_audit(report)

    # Mutate raw file
    raw_file = store.raw_retrieval_dir / "Q-1.json"
    raw_file.write_text('{"mutated": true}\n', encoding="utf-8")

    with pytest.raises((ImmutableArtifactError, ArtifactOrderError)):
        store.persist_scored(lane="retrieval", query_id="Q-1", score={"status": "HIT"})


def test_c3_delete_audited_raw_file_blocked(tmp_path: Path) -> None:
    store = _setup_clean_store(tmp_path)
    report = audit_oracle_surfaces({"request": {"query": "clean query"}})
    store.persist_oracle_audit(report)

    raw_file = store.raw_retrieval_dir / "Q-1.json"
    sidecar = raw_file.with_suffix(".json.SHA256")
    raw_file.unlink()
    sidecar.unlink()

    with pytest.raises(ArtifactOrderError):
        store.persist_scored(lane="retrieval", query_id="Q-1", score={"status": "HIT"})


def test_c3_add_clean_raw_file_after_audit_audit_stale_blocked(tmp_path: Path) -> None:
    store = _setup_clean_store(tmp_path)
    report = audit_oracle_surfaces({"request": {"query": "clean query"}})
    store.persist_oracle_audit(report)

    # Add clean raw file after audit
    store.persist_raw_retrieval(
        query_id="Q-2",
        request={"query": "clean query 2"},
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=5.0,
        runtime_lock_sha256="a" * 64,
    )

    with pytest.raises(ArtifactOrderError, match="ORACLE_AUDIT_STALE|stale|mismatch"):
        store.persist_scored(lane="retrieval", query_id="Q-1", score={"status": "HIT"})


def test_c3_leak_through_forbidden_key_detected() -> None:
    report = audit_oracle_surfaces({"notes": {"gold_evidence_ids": ["G-1"]}})
    assert report["status"] == "FAIL"
    assert report["finding_count"] == 1


def test_c3_leak_known_gold_id_through_unrelated_key_value_detected() -> None:
    report = audit_oracle_surfaces(
        {"arbitrary_field": "Reference ID: SRC-GOLD-001"},
        known_oracle_values={"SRC-GOLD-001"},
    )
    assert report["status"] == "FAIL"
    assert report["finding_count"] == 1
    assert any(f.get("matched_token") == "SRC-GOLD-001" for f in report["findings"])


def test_c3_clean_arbitrary_non_oracle_text_not_falsely_blocked() -> None:
    report = audit_oracle_surfaces(
        {"arbitrary_field": "This is completely normal text with no leaks."},
        known_oracle_values={"SRC-GOLD-001"},
    )
    assert report["status"] == "PASS"
    assert report["finding_count"] == 0


def test_c3_raw_manifest_reorder_deterministic_stable_result(tmp_path: Path) -> None:
    store = RunArtifactStore(tmp_path / RUN_ID, RUN_ID)
    store.initialize()
    store.persist_raw_retrieval(
        query_id="B-1",
        request={"query": "b"},
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=1.0,
        runtime_lock_sha256="a" * 64,
    )
    store.persist_raw_retrieval(
        query_id="A-1",
        request={"query": "a"},
        response={"results": []},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=1.0,
        runtime_lock_sha256="a" * 64,
    )
    man1 = store.compute_raw_manifest()
    man2 = store.compute_raw_manifest()
    assert man1["manifest_hash"] == man2["manifest_hash"]
    # Check that entries are sorted by path regardless of creation
    assert [e["path"] for e in man1["entries"]] == [
        "raw/retrieval/A-1.json",
        "raw/retrieval/B-1.json",
    ]


def test_c3_exact_same_sealed_raw_set_scoring_allowed(tmp_path: Path) -> None:
    store = _setup_clean_store(tmp_path)
    man = store.compute_raw_manifest()
    report = audit_oracle_surfaces(
        {"request": {"query": "clean query"}},
        raw_manifest=man,
        run_id=RUN_ID,
    )
    store.persist_oracle_audit(report)
    res = store.persist_scored(lane="retrieval", query_id="Q-1", score={"status": "HIT"})
    assert res.is_file()
