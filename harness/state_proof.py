"""E2E-controlled frozen multi-store state proof.

Verifies that paired Graph ON and Graph OFF executions ran against an unchanged,
quiescent retrieval-visible storage state covering:
- SQLite canonical store
- LanceDB vector state
- Kùzu graph state

Fails closed if any store changes between PRE and POST execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import fcntl

from harness.artifacts import canonical_json_bytes

STATE_PROOF_CONTRACT_VERSION = "mesa.state-proof.v1"
QUIESCENCE_CONTRACT_VERSION = "mesa.runtime-quiescence.v1"
_WRITER_LOCK_NAME = ".mesa-single-writer.lock"
_QUIESCENCE_QUERIES = {
    "projection": "SELECT COUNT(*) FROM projection_outbox WHERE state != 'COMPLETED'",
    "cleanup": "SELECT COUNT(*) FROM artifact_cleanup_outbox WHERE state != 'COMPLETED'",
    "dispatch": "SELECT COUNT(*) FROM dispatch_queue WHERE state != 'FINALIZED'",
    "vector_wal": "SELECT COUNT(*) FROM lancedb_wal WHERE state != 'ACKED'",
    "session_finalization": (
        "SELECT COUNT(*) FROM session_finalization_journal WHERE state != 'COMPLETED'"
    ),
    "raw_log": (
        "SELECT COUNT(*) FROM raw_logs WHERE upper(status) IN "
        "('DEFERRED', 'PROCESSING', 'PENDING', 'RETRY_PENDING', 'IN_FLIGHT')"
    ),
}


class StateProofError(RuntimeError):
    """Raised when storage state cannot be resolved or verified."""


@dataclass(frozen=True)
class StoreFingerprint:
    store_name: str
    fingerprint: str
    manifest_details: dict[str, Any]


class RuntimeQuiescenceLease:
    """Live, runner-owned proof that the MESA storage writer is fenced.

    The lease uses MESA's real single-writer lock and the same durable-backlog
    queries used by MESA rebuild preflight.  It is intentionally not
    serializable as an authority capability.
    """

    def __init__(
        self,
        *,
        run_id: str,
        storage_root: Path,
        sqlite_path: Path,
        handle: TextIO,
        lock_device: int,
        lock_inode: int,
        backlog_counts: dict[str, int],
    ) -> None:
        self.run_id = run_id
        self.storage_root = storage_root
        self.sqlite_path = sqlite_path
        self._handle = handle
        self._lock_device = lock_device
        self._lock_inode = lock_inode
        self._backlog_counts = dict(backlog_counts)
        self.acquired_at_utc = datetime.now(timezone.utc).isoformat()

    def __enter__(self) -> "RuntimeQuiescenceLease":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def release(self) -> None:
        if self._handle.closed:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()

    def _current_backlogs(self) -> dict[str, int]:
        uri = f"file:{self.sqlite_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            return {
                name: int(connection.execute(statement).fetchone()[0])
                for name, statement in _QUIESCENCE_QUERIES.items()
            }
        except (sqlite3.Error, TypeError, IndexError) as exc:
            raise StateProofError(
                f"MESA durable backlog verification failed: {exc}"
            ) from exc
        finally:
            connection.close()

    def is_held_for(self, run_id: str) -> bool:
        if run_id != self.run_id or self._handle.closed:
            return False
        try:
            expected = os.stat(
                self.storage_root / _WRITER_LOCK_NAME, follow_symlinks=False
            )
            actual = os.fstat(self._handle.fileno())
            if (expected.st_dev, expected.st_ino) != (
                self._lock_device,
                self._lock_inode,
            ) or (actual.st_dev, actual.st_ino) != (
                self._lock_device,
                self._lock_inode,
            ):
                return False
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = self._current_backlogs()
        except (OSError, StateProofError):
            return False
        return not any(current.values())

    def evidence(self) -> dict[str, Any]:
        return {
            "contract_version": QUIESCENCE_CONTRACT_VERSION,
            "run_id": self.run_id,
            "collector": "harness.state_proof.acquire_runtime_quiescence",
            "writer_lock_name": _WRITER_LOCK_NAME,
            "writer_lock_device": self._lock_device,
            "writer_lock_inode": self._lock_inode,
            "durable_backlog_counts": dict(sorted(self._backlog_counts.items())),
            "acquired_at_utc": self.acquired_at_utc,
            "result": "QUIESCENT",
        }


def acquire_runtime_quiescence(
    *,
    run_id: str,
    sqlite_path: Path | str,
    storage_root: Path | str | None = None,
) -> RuntimeQuiescenceLease:
    """Acquire MESA's real writer fence and verify all durable work is drained."""

    database = Path(sqlite_path).resolve(strict=True)
    root = Path(storage_root).resolve(strict=True) if storage_root else database.parent
    lock_path = root / _WRITER_LOCK_NAME
    if not lock_path.is_file() or lock_path.is_symlink():
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA writer lock file is unavailable"
        )
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags)
        handle = os.fdopen(descriptor, "r+", encoding="utf-8")
    except OSError as exc:
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA writer lock could not be opened"
        ) from exc
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as exc:
        handle.close()
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA storage has an active writer"
        ) from exc
    stat = os.fstat(handle.fileno())
    lease = RuntimeQuiescenceLease(
        run_id=run_id,
        storage_root=root,
        sqlite_path=database,
        handle=handle,
        lock_device=stat.st_dev,
        lock_inode=stat.st_ino,
        backlog_counts={},
    )
    try:
        counts = lease._current_backlogs()
        if any(counts.values()):
            raise StateProofError(
                "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA durable worker backlog has not drained: "
                + repr(dict(sorted(counts.items())))
            )
        lease._backlog_counts = counts
        return lease
    except Exception:
        lease.release()
        raise


@dataclass(frozen=True)
class FrozenStateProof:
    contract_version: str
    run_id: str
    sqlite_fingerprint: str
    lancedb_fingerprint: str
    kuzu_fingerprint: str
    composite_fingerprint: str
    captured_at_utc: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "run_id": self.run_id,
            "sqlite_fingerprint": self.sqlite_fingerprint,
            "lancedb_fingerprint": self.lancedb_fingerprint,
            "kuzu_fingerprint": self.kuzu_fingerprint,
            "composite_fingerprint": self.composite_fingerprint,
            "captured_at_utc": self.captured_at_utc,
            "details": self.details,
        }


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _directory_manifest(dir_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Deterministically hash all regular files in a directory."""
    if not dir_path.is_dir():
        raise StateProofError(f"directory does not exist: {dir_path}")

    entries: list[dict[str, Any]] = []
    for file_path in sorted(dir_path.rglob("*")):
        if file_path.is_file() and not file_path.name.endswith(".lock"):
            rel = file_path.relative_to(dir_path).as_posix()
            size = file_path.stat().st_size
            digest = _file_sha256(file_path)
            entries.append({"path": rel, "size": size, "sha256": digest})

    manifest_hash = hashlib.sha256(canonical_json_bytes(entries)).hexdigest()
    return f"sha256:{manifest_hash}", entries


def fingerprint_sqlite(sqlite_path: Path | str) -> StoreFingerprint:
    """Compute deterministic SQLite table-level and file-level fingerprint."""
    path = Path(sqlite_path)
    if not path.is_file():
        raise StateProofError(f"SQLite database file not found: {path}")

    # Read-only connect
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'view', 'trigger', 'index') "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        schema_rows = cursor.fetchall()

        cursor.execute("PRAGMA schema_version")
        schema_version = cursor.fetchone()[0]

        cursor.execute("PRAGMA data_version")
        data_version = cursor.fetchone()[0]

        table_rows = {}
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        table_names = [r[0] for r in cursor.fetchall()]
        for tbl in table_names:
            cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
            count = cursor.fetchone()[0]
            # Sample row content summary for tables under 10,000 rows
            row_hash = None
            if count <= 10000:
                cursor.execute(f"SELECT * FROM {tbl} ORDER BY rowid")
                rows_data = cursor.fetchall()
                row_hash = hashlib.sha256(canonical_json_bytes(rows_data)).hexdigest()
            table_rows[tbl] = {"count": count, "content_hash": row_hash}

        conn.close()
    except Exception as exc:
        raise StateProofError(f"SQLite read-only fingerprinting failed: {exc}") from exc

    # File-level hashes for db and wal
    file_hashes = {"db": _file_sha256(path)}
    wal_path = path.with_name(path.name + "-wal")
    if wal_path.is_file() and wal_path.stat().st_size > 0:
        file_hashes["wal"] = _file_sha256(wal_path)

    manifest = {
        "schema_version": schema_version,
        "data_version": data_version,
        "schema_items": len(schema_rows),
        "tables": table_rows,
        "files": file_hashes,
    }
    digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    return StoreFingerprint(
        store_name="sqlite",
        fingerprint=f"sha256:{digest}",
        manifest_details=manifest,
    )


def fingerprint_lancedb(lancedb_dir: Path | str) -> StoreFingerprint:
    """Compute deterministic directory manifest fingerprint of LanceDB vector store."""
    path = Path(lancedb_dir)
    digest, entries = _directory_manifest(path)
    return StoreFingerprint(
        store_name="lancedb",
        fingerprint=digest,
        manifest_details={"file_count": len(entries), "entries": entries},
    )


def fingerprint_kuzu(kuzu_dir: Path | str) -> StoreFingerprint:
    """Compute deterministic directory manifest fingerprint of Kùzu graph store."""
    path = Path(kuzu_dir)
    digest, entries = _directory_manifest(path)
    return StoreFingerprint(
        store_name="kuzu",
        fingerprint=digest,
        manifest_details={"file_count": len(entries), "entries": entries},
    )


def capture_frozen_state_proof(
    *,
    run_id: str,
    sqlite_path: Path | str,
    lancedb_dir: Path | str,
    kuzu_dir: Path | str,
) -> FrozenStateProof:
    """Capture a composite state proof across SQLite, LanceDB, and Kùzu."""

    sql_fp = fingerprint_sqlite(sqlite_path)
    vec_fp = fingerprint_lancedb(lancedb_dir)
    kuzu_fp = fingerprint_kuzu(kuzu_dir)

    composite_payload = {
        "sqlite": sql_fp.fingerprint,
        "lancedb": vec_fp.fingerprint,
        "kuzu": kuzu_fp.fingerprint,
    }
    composite_hash = (
        f"sha256:{hashlib.sha256(canonical_json_bytes(composite_payload)).hexdigest()}"
    )

    return FrozenStateProof(
        contract_version=STATE_PROOF_CONTRACT_VERSION,
        run_id=run_id,
        sqlite_fingerprint=sql_fp.fingerprint,
        lancedb_fingerprint=vec_fp.fingerprint,
        kuzu_fingerprint=kuzu_fp.fingerprint,
        composite_fingerprint=composite_hash,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
        details={
            "sqlite": sql_fp.manifest_details,
            "lancedb_files": len(vec_fp.manifest_details.get("entries", [])),
            "kuzu_files": len(kuzu_fp.manifest_details.get("entries", [])),
        },
    )


def verify_quiescence_evidence(
    quiescence_evidence: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Reject caller-authored quiescence claims.

    Kept as a compatibility diagnostic for callers which previously supplied
    dictionaries.  Official authority is available only through
    :func:`acquire_runtime_quiescence`.
    """

    if isinstance(quiescence_evidence, dict) and quiescence_evidence:
        return False, "caller-supplied quiescence assertions are non-authoritative"
    return False, "trusted runtime quiescence lease absent"


def verify_store_quiescence(
    pre_proof: FrozenStateProof,
    post_proof: FrozenStateProof,
    quiescence_lease: RuntimeQuiescenceLease | None = None,
) -> tuple[bool, str, bool]:
    """Verify that PRE and POST state proofs are unchanged and evaluate quiescence.

    Returns (state_unchanged, reason, quiescence_verified).
    """

    if pre_proof.sqlite_fingerprint != post_proof.sqlite_fingerprint:
        return (
            False,
            f"BLOCKED_BY_RUNTIME_STATE_PROOF: SQLite store mutated during paired execution "
            f"({pre_proof.sqlite_fingerprint} != {post_proof.sqlite_fingerprint})",
            False,
        )
    if pre_proof.lancedb_fingerprint != post_proof.lancedb_fingerprint:
        return (
            False,
            f"BLOCKED_BY_RUNTIME_STATE_PROOF: LanceDB vector store mutated during paired execution "
            f"({pre_proof.lancedb_fingerprint} != {post_proof.lancedb_fingerprint})",
            False,
        )
    if pre_proof.kuzu_fingerprint != post_proof.kuzu_fingerprint:
        return (
            False,
            f"BLOCKED_BY_RUNTIME_STATE_PROOF: Kùzu graph store mutated during paired execution "
            f"({pre_proof.kuzu_fingerprint} != {post_proof.kuzu_fingerprint})",
            False,
        )
    if pre_proof.composite_fingerprint != post_proof.composite_fingerprint:
        return (
            False,
            "BLOCKED_BY_RUNTIME_STATE_PROOF: composite store fingerprint mismatch",
            False,
        )

    quiescent = type(
        quiescence_lease
    ) is RuntimeQuiescenceLease and quiescence_lease.is_held_for(pre_proof.run_id)
    return True, "RETRIEVAL_STATE_UNCHANGED", quiescent


def write_sealed_state_proof(
    run_dir: Path | str,
    *,
    run_id: str,
    pre_proof: FrozenStateProof,
    post_proof: FrozenStateProof,
    store_locations: dict[str, str],
    dataset_identity: str = "dataset-legal-1",
    freeze_identity: str = "freeze-v1",
    quiescence_lease: RuntimeQuiescenceLease | None = None,
    execution_id: str | None = None,
) -> tuple[Path, str]:
    """Write authoritative sealed state proof artifact into raw/state lane."""
    raw_state_dir = Path(run_dir) / "raw" / "state"
    raw_state_dir.mkdir(parents=True, exist_ok=True)
    target_path = raw_state_dir / "state-proof.json"

    unchanged, reason, quiescent = verify_store_quiescence(
        pre_proof, post_proof, quiescence_lease=quiescence_lease
    )

    payload = {
        "schema_version": "1.0",
        "run_id": run_id,
        "execution_id": execution_id,
        "lane": "state",
        "contract_version": STATE_PROOF_CONTRACT_VERSION,
        "dataset_identity": dataset_identity,
        "freeze_identity": freeze_identity,
        "store_locations": store_locations,
        "pre_composite_fingerprint": pre_proof.composite_fingerprint,
        "post_composite_fingerprint": post_proof.composite_fingerprint,
        "sqlite_fingerprint": pre_proof.sqlite_fingerprint,
        "lancedb_fingerprint": pre_proof.lancedb_fingerprint,
        "kuzu_fingerprint": pre_proof.kuzu_fingerprint,
        "retrieval_state_unchanged": unchanged,
        "quiescence_evidence": (
            quiescence_lease.evidence() if quiescence_lease is not None else {}
        ),
        "quiescence_verified": quiescent,
        "collector_version": "harness.state_proof.v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "pre_state": pre_proof.to_dict(),
        "post_state": post_proof.to_dict(),
    }

    serialized = (
        json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")
    target_path.write_bytes(serialized)
    digest = hashlib.sha256(serialized).hexdigest()
    target_path.with_suffix(target_path.suffix + ".SHA256").write_text(
        f"{digest}  {target_path.name}\n", encoding="utf-8", newline="\n"
    )
    return target_path, digest
