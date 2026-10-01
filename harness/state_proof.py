"""E2E-controlled paired multi-store state-stability proof.

Verifies that paired Graph ON and Graph OFF executions ran against an unchanged,
retrieval-visible storage state covering:
- SQLite canonical store
- LanceDB vector state
- Kùzu graph state

The live MESA ``combined`` runtime owns its single-writer lock for its entire
lifetime.  E2E therefore observes that ownership; it never tries to acquire the
same lock.  This module does not claim runtime quiescence.  It proves the
narrower property needed by B11: the same runtime served both sides of a pair,
durable mutation markers did not advance, and all three stores were unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.artifacts import canonical_json_bytes

STATE_PROOF_CONTRACT_VERSION = "mesa.state-proof.v2"
STATE_STABILITY_CONTRACT_VERSION = "mesa.paired-state-stability.v1"
SQLITE_FINGERPRINT_ALGORITHM_VERSION = "mesa.sqlite-state-fingerprint.v2"
_SQLITE_FETCH_BATCH_SIZE = 1_000
_WRITER_LOCK_NAME = ".mesa-single-writer.lock"
_STATE_GUARD_TOKEN = object()
_DURABLE_BACKLOG_QUERIES = {
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

_MUTATION_MARKER_TABLES = (
    "memory_mutations",
    "pipeline_run_events",
    "projection_attempts",
    "dispatch_receipts",
    "dispatch_completion_receipts",
    "v4_idempotency_receipts",
)


class StateProofError(RuntimeError):
    """Raised when storage state cannot be resolved or verified."""


@dataclass(frozen=True)
class StoreFingerprint:
    store_name: str
    fingerprint: str
    manifest_details: dict[str, Any]


@dataclass(frozen=True)
class RuntimeWriterObservation:
    """Identity of the live process holding MESA's lifetime writer lock."""

    owner: str
    pid: int
    process_start_ticks: int
    lock_device: int
    lock_inode: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "pid": self.pid,
            "process_start_ticks": self.process_start_ticks,
            "writer_lock_name": _WRITER_LOCK_NAME,
            "writer_lock_device": self.lock_device,
            "writer_lock_inode": self.lock_inode,
            "lock_observation": "PROC_LOCK_HELD_BY_RUNTIME",
        }


def _proc_start_ticks(pid: int) -> int:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields_after_name = stat_text[stat_text.rfind(")") + 2 :].split()
        return int(fields_after_name[19])
    except (OSError, UnicodeError, ValueError, IndexError) as exc:
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA writer process identity is unavailable"
        ) from exc


def _proc_has_lock(*, pid: int, lock_device: int, lock_inode: int) -> bool:
    expected_major = os.major(lock_device)
    expected_minor = os.minor(lock_device)
    try:
        lines = Path("/proc/locks").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: host lock observations are unavailable"
        ) from exc
    for line in lines:
        fields = line.split()
        if len(fields) < 6 or fields[1] != "FLOCK" or fields[3] != "WRITE":
            continue
        try:
            lock_pid = int(fields[4])
            major_hex, minor_hex, inode_text = fields[5].split(":", 2)
            identity = (
                lock_pid,
                int(major_hex, 16),
                int(minor_hex, 16),
                int(inode_text),
            )
        except (ValueError, IndexError):
            continue
        if identity == (pid, expected_major, expected_minor, lock_inode):
            return True
    return False


def _proc_has_lock_fd(*, pid: int, lock_device: int, lock_inode: int) -> bool:
    try:
        descriptors = list(Path(f"/proc/{pid}/fd").iterdir())
    except OSError as exc:
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA writer descriptors are unavailable"
        ) from exc
    for descriptor in descriptors:
        try:
            current = descriptor.stat()
        except OSError:
            continue
        if (current.st_dev, current.st_ino) == (lock_device, lock_inode):
            return True
    return False


def _observe_runtime_writer(storage_root: Path) -> RuntimeWriterObservation:
    """Observe MESA's existing FLOCK without attempting to acquire it."""

    lock_path = storage_root / _WRITER_LOCK_NAME
    if not lock_path.is_file() or lock_path.is_symlink():
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA writer lock file is unavailable"
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            metadata_text = handle.read()
            lock_stat = os.fstat(handle.fileno())
        metadata = {}
        for line in metadata_text.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                metadata[key] = value
        owner = metadata.get("owner", "")
        pid = int(metadata.get("pid", ""))
    except (OSError, UnicodeError, ValueError) as exc:
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA writer lock metadata is invalid"
        ) from exc
    if owner != "combined-runtime" or pid <= 0:
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: expected combined runtime does not own writer lock"
        )
    if not _proc_has_lock(
        pid=pid, lock_device=lock_stat.st_dev, lock_inode=lock_stat.st_ino
    ) or not _proc_has_lock_fd(
        pid=pid, lock_device=lock_stat.st_dev, lock_inode=lock_stat.st_ino
    ):
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: writer lock is not held by expected runtime process"
        )
    return RuntimeWriterObservation(
        owner=owner,
        pid=pid,
        process_start_ticks=_proc_start_ticks(pid),
        lock_device=lock_stat.st_dev,
        lock_inode=lock_stat.st_ino,
    )


def _read_sqlite_observations(
    sqlite_path: Path,
) -> tuple[dict[str, int], dict[str, dict[str, int]], str]:
    uri = f"file:{sqlite_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        backlogs = {
            name: int(connection.execute(statement).fetchone()[0])
            for name, statement in _DURABLE_BACKLOG_QUERIES.items()
        }
        markers: dict[str, dict[str, int]] = {}
        for table_name in _MUTATION_MARKER_TABLES:
            row = connection.execute(
                f"SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM {table_name}"
            ).fetchone()
            if row is None:
                raise StateProofError(
                    f"mutation marker table {table_name!r} returned no result"
                )
            markers[table_name] = {"row_count": int(row[0]), "max_rowid": int(row[1])}
    except (sqlite3.Error, TypeError, ValueError, IndexError) as exc:
        raise StateProofError(
            f"BLOCKED_BY_RUNTIME_STATE_PROOF: MESA runtime observation failed: {exc}"
        ) from exc
    finally:
        connection.close()
    marker_sha256 = hashlib.sha256(canonical_json_bytes(markers)).hexdigest()
    return backlogs, markers, marker_sha256


class PairedStateStabilityGuard:
    """Runner-owned capability for a live-runtime paired state proof.

    The guard owns no MESA lock.  It binds PRE observations to POST observations
    and is intentionally not constructible as a caller-authored boolean claim.
    """

    def __init__(
        self,
        *,
        _token: object,
        run_id: str,
        storage_root: Path,
        sqlite_path: Path,
        writer_observation: RuntimeWriterObservation,
        backlog_counts: dict[str, int],
        mutation_marker: dict[str, dict[str, int]],
        mutation_marker_sha256: str,
    ) -> None:
        if _token is not _STATE_GUARD_TOKEN:
            raise TypeError("PairedStateStabilityGuard is runner-owned")
        self.run_id = run_id
        self.storage_root = storage_root
        self.sqlite_path = sqlite_path
        self._pre_writer = writer_observation
        self._pre_backlogs = dict(backlog_counts)
        self._pre_marker = mutation_marker
        self._pre_marker_sha256 = mutation_marker_sha256
        self._post_writer: RuntimeWriterObservation | None = None
        self._post_backlogs: dict[str, int] | None = None
        self._post_marker: dict[str, dict[str, int]] | None = None
        self._post_marker_sha256: str | None = None
        self._verified = False
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self.completed_at_utc: str | None = None

    def __enter__(self) -> "PairedStateStabilityGuard":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def finalize(self, run_id: str) -> bool:
        if run_id != self.run_id:
            return False
        try:
            post_writer = _observe_runtime_writer(self.storage_root)
            post_backlogs, post_marker, post_marker_sha256 = _read_sqlite_observations(
                self.sqlite_path
            )
        except (OSError, StateProofError):
            return False
        self._post_writer = post_writer
        self._post_backlogs = post_backlogs
        self._post_marker = post_marker
        self._post_marker_sha256 = post_marker_sha256
        self.completed_at_utc = datetime.now(timezone.utc).isoformat()
        self._verified = (
            post_writer == self._pre_writer
            and not any(self._pre_backlogs.values())
            and not any(post_backlogs.values())
            and post_marker_sha256 == self._pre_marker_sha256
        )
        return self._verified

    def is_verified_for(self, run_id: str) -> bool:
        if run_id != self.run_id or not self._verified:
            return False
        try:
            writer = _observe_runtime_writer(self.storage_root)
            backlogs, _marker, marker_sha256 = _read_sqlite_observations(
                self.sqlite_path
            )
        except StateProofError:
            return False
        return (
            writer == self._pre_writer
            and not any(backlogs.values())
            and marker_sha256 == self._pre_marker_sha256
        )

    def evidence(self) -> dict[str, Any]:
        if not self._verified or self._post_writer is None:
            raise StateProofError(
                "BLOCKED_BY_RUNTIME_STATE_PROOF: paired state guard is not verified"
            )
        return {
            "contract_version": STATE_STABILITY_CONTRACT_VERSION,
            "run_id": self.run_id,
            "collector": "harness.state_proof.establish_paired_state_stability",
            "proof_mode": "stable_state_pair",
            "writer_lock_acquired_by_e2e": False,
            "pre_writer_observation": self._pre_writer.to_dict(),
            "post_writer_observation": self._post_writer.to_dict(),
            "pre_durable_backlog_counts": dict(sorted(self._pre_backlogs.items())),
            "post_durable_backlog_counts": dict(
                sorted((self._post_backlogs or {}).items())
            ),
            "pre_mutation_marker": self._pre_marker,
            "post_mutation_marker": self._post_marker,
            "pre_mutation_marker_sha256": self._pre_marker_sha256,
            "post_mutation_marker_sha256": self._post_marker_sha256,
            "runtime_quiescence_verified": False,
            "pair_state_stability_verified": True,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
        }


def establish_paired_state_stability(
    *,
    run_id: str,
    sqlite_path: Path | str,
    storage_root: Path | str | None = None,
) -> PairedStateStabilityGuard:
    """Begin a live-runtime state proof without acquiring MESA's writer lock."""

    database = Path(sqlite_path).resolve(strict=True)
    root = Path(storage_root).resolve(strict=True) if storage_root else database.parent
    writer = _observe_runtime_writer(root)
    backlogs, marker, marker_sha256 = _read_sqlite_observations(database)
    if any(backlogs.values()):
        raise StateProofError(
            "BLOCKED_BY_RUNTIME_STATE_PROOF: MESA durable worker backlog has not drained: "
            + repr(dict(sorted(backlogs.items())))
        )
    return PairedStateStabilityGuard(
        _token=_STATE_GUARD_TOKEN,
        run_id=run_id,
        storage_root=root,
        sqlite_path=database,
        writer_observation=writer,
        backlog_counts=backlogs,
        mutation_marker=marker,
        mutation_marker_sha256=marker_sha256,
    )


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


def _quote_ident(ident: str) -> str:
    """Safely quote a SQLite identifier (table or column name)."""
    return '"' + ident.replace('"', '""') + '"'


def _canonical_sqlite_val(val: Any) -> Any:
    """Canonicalize a SQLite cell value for deterministic JSON serialization."""
    if isinstance(val, bytes):
        return {"$blob": val.hex()}
    if val is None or isinstance(val, (int, float, str)):
        return val
    raise StateProofError(f"unsupported SQLite value type: {type(val).__name__}")


def _table_order_columns(cursor: sqlite3.Cursor, tbl: str) -> list[str]:
    """Determine deterministic ordering columns for a table.

    1. Put explicit PRIMARY KEY columns first, in PK ordinal order.
    2. Use every remaining declared column as a deterministic tie-breaker.
    3. If no columns are declared, fallback to 'rowid' if table supports rowid.
    """
    cursor.execute(f"PRAGMA table_info({_quote_ident(tbl)})")
    cols_info = cursor.fetchall()
    # cols_info items: (cid, name, type, notnull, dflt_value, pk)
    # pk > 0 indicates PK column, and its value is the 1-based PK order
    pk_cols = [
        col[1]
        for col in sorted([c for c in cols_info if c[5] > 0], key=lambda c: c[5])
    ]
    all_cols = [col[1] for col in cols_info]
    if pk_cols:
        pk_set = set(pk_cols)
        return pk_cols + [col for col in all_cols if col not in pk_set]

    if all_cols:
        return all_cols

    is_without_rowid = False
    try:
        cursor.execute(f"PRAGMA table_list({_quote_ident(tbl)})")
        for row in cursor.fetchall():
            if len(row) >= 5 and row[1] == tbl:
                is_without_rowid = bool(row[4])
                break
    except sqlite3.OperationalError:
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        )
        sql_row = cursor.fetchone()
        if sql_row and sql_row[0]:
            is_without_rowid = bool(
                re.search(r"\bWITHOUT\s+ROWID\b", sql_row[0], re.IGNORECASE)
            )

    if not is_without_rowid:
        return ["rowid"]
    raise StateProofError(
        f"SQLite table {tbl!r} has neither declared columns nor a usable rowid"
    )


def _hash_ordered_sqlite_rows(
    cursor: sqlite3.Cursor,
    *,
    tbl: str,
    order_cols: list[str],
) -> tuple[int, str]:
    """Stream a canonical JSON row array in deterministic order.

    Streaming preserves the historical canonical JSON representation while
    avoiding an unbounded in-memory materialization for tables above the old
    10,000-row threshold.
    """
    order_clause = ", ".join(_quote_ident(col) for col in order_cols)
    cursor.execute(
        f"SELECT * FROM {_quote_ident(tbl)} ORDER BY {order_clause}"
    )

    hasher = hashlib.sha256()
    hasher.update(b"[")
    row_count = 0
    first = True
    while True:
        batch = cursor.fetchmany(_SQLITE_FETCH_BATCH_SIZE)
        if not batch:
            break
        for raw_row in batch:
            canonical_row = [_canonical_sqlite_val(val) for val in raw_row]
            if not first:
                hasher.update(b",")
            hasher.update(canonical_json_bytes(canonical_row))
            first = False
            row_count += 1
    hasher.update(b"]")
    return row_count, hasher.hexdigest()


def fingerprint_sqlite(sqlite_path: Path | str) -> StoreFingerprint:
    """Compute deterministic SQLite table-level and logical state fingerprint."""
    path = Path(sqlite_path)
    if not path.is_file():
        raise StateProofError(f"SQLite database file not found: {path}")

    # Read-only connect with explicit snapshot isolation
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.isolation_level = None
        conn.execute("BEGIN DEFERRED")
        cursor = conn.cursor()

        try:
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

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            table_names = [r[0] for r in cursor.fetchall()]
        except Exception as exc:
            raise StateProofError(
                f"SQLite read-only fingerprinting failed (schema_metadata): {exc}"
            ) from exc

        table_rows: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {_quote_ident(tbl)}")
                count = cursor.fetchone()[0]
            except Exception as exc:
                raise StateProofError(
                    f"SQLite read-only fingerprinting failed on table {tbl!r} (count): {exc}"
                ) from exc

            try:
                order_cols = _table_order_columns(cursor, tbl)
                hashed_count, row_hash = _hash_ordered_sqlite_rows(
                    cursor,
                    tbl=tbl,
                    order_cols=order_cols,
                )
                if hashed_count != count:
                    raise StateProofError(
                        f"row count changed inside the read snapshot "
                        f"({count} != {hashed_count})"
                    )
            except Exception as exc:
                raise StateProofError(
                    f"SQLite read-only fingerprinting failed on table {tbl!r} (query_content): {exc}"
                ) from exc

            table_rows[tbl] = {"count": count, "content_hash": row_hash}

    except StateProofError:
        raise
    except Exception as exc:
        raise StateProofError(f"SQLite read-only fingerprinting failed: {exc}") from exc
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()

    # File-level hashes for db and wal
    file_hashes = {"db": _file_sha256(path)}
    wal_path = path.with_name(path.name + "-wal")
    if wal_path.is_file() and wal_path.stat().st_size > 0:
        file_hashes["wal"] = _file_sha256(wal_path)

    schema_hash = hashlib.sha256(canonical_json_bytes(schema_rows)).hexdigest()
    logical_manifest = {
        "fingerprint_algorithm": SQLITE_FINGERPRINT_ALGORITHM_VERSION,
        "schema_version": schema_version,
        "data_version": data_version,
        "schema_items": len(schema_rows),
        "schema_hash": schema_hash,
        "tables": table_rows,
    }
    digest = hashlib.sha256(canonical_json_bytes(logical_manifest)).hexdigest()
    manifest_details = {
        **logical_manifest,
        "files": file_hashes,
    }
    return StoreFingerprint(
        store_name="sqlite",
        fingerprint=f"sha256:{digest}",
        manifest_details=manifest_details,
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
    dictionaries.  This compatibility diagnostic never promotes a caller
    assertion into either quiescence or paired state-stability authority.
    """

    if isinstance(quiescence_evidence, dict) and quiescence_evidence:
        return False, "caller-supplied quiescence assertions are non-authoritative"
    return False, "native runtime freeze evidence absent"


def verify_store_stability(
    pre_proof: FrozenStateProof,
    post_proof: FrozenStateProof,
    state_guard: PairedStateStabilityGuard | None = None,
) -> tuple[bool, str, bool]:
    """Verify PRE/POST stores and the runner-owned live-runtime observations.

    Returns (state_unchanged, reason, pair_state_stability_verified).
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

    pair_stable = type(
        state_guard
    ) is PairedStateStabilityGuard and state_guard.finalize(pre_proof.run_id)
    if state_guard is not None and not pair_stable:
        return (
            False,
            "BLOCKED_BY_RUNTIME_STATE_PROOF: runtime identity, durable backlog, "
            "or mutation marker changed during paired execution",
            False,
        )
    return True, "RETRIEVAL_STATE_UNCHANGED", pair_stable


def write_sealed_state_proof(
    run_dir: Path | str,
    *,
    run_id: str,
    pre_proof: FrozenStateProof,
    post_proof: FrozenStateProof,
    store_locations: dict[str, str],
    dataset_identity: str = "dataset-legal-1",
    freeze_identity: str = "freeze-v1",
    state_guard: PairedStateStabilityGuard | None = None,
    execution_id: str | None = None,
) -> tuple[Path, str]:
    """Write authoritative sealed state proof artifact into raw/state lane."""
    raw_state_dir = Path(run_dir) / "raw" / "state"
    raw_state_dir.mkdir(parents=True, exist_ok=True)
    target_path = raw_state_dir / "state-proof.json"

    unchanged, reason, pair_stable = verify_store_stability(
        pre_proof, post_proof, state_guard=state_guard
    )
    if not unchanged:
        raise StateProofError(reason)
    stability_evidence = state_guard.evidence() if pair_stable else {}

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
        "proof_mode": "stable_state_pair" if pair_stable else "unverified",
        "state_stability_evidence": stability_evidence,
        "pair_state_stability_verified": pair_stable,
        "runtime_quiescence_verified": False,
        "quiescence_verified": False,
        "collector_version": "harness.state_proof.v2",
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
