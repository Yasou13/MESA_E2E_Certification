"""Deterministic attack matrix for authoritative B4-B8 metric producers.

Proves fail-closed behavior against fabricated, mismatched, mutated, or stale
upstream claims per Section 20 requirements.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from harness.metric_producers import (
    PRODUCTION_METRIC_PRODUCERS,
    ProducerContext,
    ProducerIntegrityError,
)

RUN_ID = "RUN-20261009T120000Z-b4b8"
OTHER_RUN_ID = "RUN-20261009T111111Z-other"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
GATE_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json"


def _ctx(tmp_path: Path, run_id: str = RUN_ID) -> ProducerContext:
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
        "run_id": run_id,
        "manifest_hash": manifest_hash,
        "entries": entries,
    }
    p = tmp_path / "raw-manifest.json"
    p_bytes = (json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    p.write_bytes(p_bytes)
    p_sha = hashlib.sha256(p_bytes).hexdigest()
    p.with_suffix(p.suffix + ".SHA256").write_text(f"{p_sha}  {p.name}\n", encoding="utf-8")

    return ProducerContext(
        run_dir=tmp_path,
        run_id=run_id,
        freeze_path=tmp_path / "contract-freeze.json",
        checksum_path=tmp_path / "contract-freeze.SHA256",
        repository_root=tmp_path,
        current_repository_shas={},
        raw_manifest_hash=manifest_hash,
        gate_config_path=GATE_CONFIG_PATH,
    )


def _seal_artifact(tmp_path: Path, filename: str, payload: dict[str, Any]) -> Path:
    file_path = tmp_path / filename
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("run_id", RUN_ID)
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    file_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    file_path.with_suffix(file_path.suffix + ".SHA256").write_text(
        f"{digest}  {file_path.name}\n", encoding="utf-8"
    )
    return file_path


class _MockExecutionSession:
    def __init__(self, run_id: str = RUN_ID) -> None:
        self.run_id = run_id

    def verify_raw_manifest(self, manifest: dict[str, Any], expected_hash: str) -> None:
        pass

    def verify_derived_artifact(self, path: Path, artifact_type: str) -> None:
        # Passes if artifact is runner-owned
        pass


class _ForeignExecutionSession:
    def verify_raw_manifest(self, manifest: dict[str, Any], expected_hash: str) -> None:
        pass

    def verify_derived_artifact(self, path: Path, artifact_type: str) -> None:
        raise ValueError("artifact belongs to a different foreign run execution")


# =========================================================================
# ATTACK TEST 1: Fabricated COMMITTED JSON without runner authority
# =========================================================================
def test_b6_fabricated_committed_json_fails_closed(tmp_path: Path) -> None:
    _seal_artifact(
        tmp_path,
        "native-canary.json",
        {
            "publisher_component": "MESA_Data",
            "publish_route": "/v4/memory/insert",
            "diagnostic_bridge_used": False,
            "mutation_state": "COMMITTED",
            "source_chunk_id": "chunk-attack-1",
            "search_source_chunk_id": "chunk-attack-1",
            "logical_count_before_retry": 10,
            "logical_count_after_retry": 10,
        },
    )
    # Official mode without runner-owned registration must fail
    official_ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_ForeignExecutionSession(),
    )
    with pytest.raises(ProducerIntegrityError, match="not runner-owned"):
        PRODUCTION_METRIC_PRODUCERS["B6"](official_ctx)


# =========================================================================
# ATTACK TEST 2: Mutation ID / source chunk ID mismatch
# =========================================================================
def test_b6_source_chunk_id_mismatch_fails(tmp_path: Path) -> None:
    _seal_artifact(
        tmp_path,
        "native-canary.json",
        {
            "publisher_component": "MESA_Data",
            "publish_route": "/v4/memory/insert",
            "diagnostic_bridge_used": False,
            "mutation_state": "COMMITTED",
            "source_chunk_id": "chunk-1",
            "search_source_chunk_id": "chunk-different",  # Mismatch!
            "logical_count_before_retry": 10,
            "logical_count_after_retry": 10,
        },
    )
    ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_MockExecutionSession(),
    )
    result = PRODUCTION_METRIC_PRODUCERS["B6"](ctx)
    assert result.observed["canary_passed"] is False


# =========================================================================
# ATTACK TEST 3: Manifest / Run-ID substitution mismatch
# =========================================================================
def test_run_id_mismatch_in_raw_manifest_fails_closed(tmp_path: Path) -> None:
    from harness.metric_producers import _load_and_verify_raw_manifest

    ctx = _ctx(tmp_path, run_id=RUN_ID)
    manifest_path = tmp_path / "raw-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = OTHER_RUN_ID
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    m_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path.with_suffix(manifest_path.suffix + ".SHA256").write_text(
        f"{m_sha}  {manifest_path.name}\n", encoding="utf-8"
    )

    with pytest.raises(ProducerIntegrityError, match="run_id mismatch"):
        _load_and_verify_raw_manifest(ctx)


def test_artifact_with_wrong_run_id_fails_closed(tmp_path: Path) -> None:
    _seal_artifact(
        tmp_path,
        "corpus-integrity.json",
        {"run_id": OTHER_RUN_ID, "items": [{"document_id": "doc-1", "raw_sha256": "0" * 64, "canonical_sha256": "0" * 64}]},
    )
    ctx = replace(_ctx(tmp_path), execution_mode="official", execution_session=_MockExecutionSession())
    with pytest.raises(ProducerIntegrityError, match="RUN_ID mismatch"):
        PRODUCTION_METRIC_PRODUCERS["B4"](ctx)


# =========================================================================
# ATTACK TEST 4: Stale artifact from earlier certification run
# =========================================================================
def test_b7_stale_foreign_authority_artifact_fails_closed(tmp_path: Path) -> None:
    _seal_artifact(
        tmp_path,
        "delivery-evidence.json",
        {
            "planned_source_chunk_ids": ["chunk-1"],
            "deliveries": [
                {
                    "source_chunk_id": "chunk-1",
                    "terminal_state": "COMMITTED",
                    "mesa_chunk_id": "mesa-1",
                    "mutation_id": "mut-1",
                }
            ],
        },
    )
    stale_ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_ForeignExecutionSession(),
    )
    with pytest.raises(ProducerIntegrityError, match="not runner-owned"):
        PRODUCTION_METRIC_PRODUCERS["B7"](stale_ctx)


# =========================================================================
# ATTACK TEST 5: Wrong or empty dataset identity in B7
# =========================================================================
def test_b7_empty_dataset_identity_fails(tmp_path: Path) -> None:
    _seal_artifact(
        tmp_path,
        "delivery-evidence.json",
        {
            "dataset": "",  # Empty dataset identity
            "planned_source_chunk_ids": ["chunk-1"],
            "deliveries": [
                {
                    "source_chunk_id": "chunk-1",
                    "terminal_state": "COMMITTED",
                    "mesa_chunk_id": "mesa-1",
                    "mutation_id": "mut-1",
                }
            ],
        },
    )
    ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_MockExecutionSession(),
    )
    with pytest.raises(ProducerIntegrityError, match="dataset identity is empty"):
        PRODUCTION_METRIC_PRODUCERS["B7"](ctx)


# =========================================================================
# ATTACK TEST 6: Wrong corpus hash / malformed corpus items in B4
# =========================================================================
def test_b4_malformed_corpus_items_fails_closed(tmp_path: Path) -> None:
    _seal_artifact(
        tmp_path,
        "corpus-integrity.json",
        {
            "items": [
                {"document_id": "doc-1", "raw_sha256": "0" * 64, "canonical_sha256": "wrong"}
            ]
        },
    )
    ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_MockExecutionSession(),
    )
    with pytest.raises(ProducerIntegrityError, match="raw_path|malformed|invalid"):
        PRODUCTION_METRIC_PRODUCERS["B4"](ctx)


# =========================================================================
# ATTACK TEST 7: Restart artifact created before restart (chronology violation)
# =========================================================================
def test_b8_chronology_violation_fails_persistence(tmp_path: Path) -> None:
    _seal_artifact(
        tmp_path,
        "restart-idempotency.json",
        {
            "before_restart_ts": 1700000050.0,
            "after_restart_ts": 1700000000.0,  # after_ts is BEFORE before_ts!
            "before_restart_probe": {"fingerprint": "f" * 64},
            "after_restart_probe": {"fingerprint": "f" * 64},
            "restart_observed": True,
            "logical_count_before_republish": 5,
            "logical_count_after_republish": 5,
            "stable_idempotency_key": True,
            "republish_terminal_state": "COMMITTED",
        },
    )
    ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_MockExecutionSession(),
    )
    result = PRODUCTION_METRIC_PRODUCERS["B8"](ctx)
    assert result.observed["restart_persistence_proven"] is False


# =========================================================================
# ATTACK TEST 8: Evidence changed after seal (sidecar mismatch)
# =========================================================================
def test_evidence_modified_after_seal_fails_closed(tmp_path: Path) -> None:
    path = _seal_artifact(
        tmp_path,
        "restart-idempotency.json",
        {
            "before_restart_probe": {"fingerprint": "f" * 64},
            "after_restart_probe": {"fingerprint": "f" * 64},
            "restart_observed": True,
            "logical_count_before_republish": 5,
            "logical_count_after_republish": 5,
            "stable_idempotency_key": True,
            "republish_terminal_state": "COMMITTED",
        },
    )
    # Mutate the file without updating sidecar
    path.write_bytes(path.read_bytes() + b"\n/* tampered */\n")

    ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_MockExecutionSession(),
    )
    with pytest.raises(ProducerIntegrityError, match="seal mismatch"):
        PRODUCTION_METRIC_PRODUCERS["B8"](ctx)


# =========================================================================
# ATTACK TEST 9: Missing authoritative evidence file
# =========================================================================
def test_missing_authoritative_artifact_fails_closed(tmp_path: Path) -> None:
    ctx = replace(
        _ctx(tmp_path),
        execution_mode="official",
        execution_session=_MockExecutionSession(),
    )
    with pytest.raises(ProducerIntegrityError, match="missing"):
        PRODUCTION_METRIC_PRODUCERS["B6"](ctx)
