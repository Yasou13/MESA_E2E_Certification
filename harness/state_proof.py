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
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.artifacts import canonical_json_bytes


STATE_PROOF_CONTRACT_VERSION = "mesa.state-proof.v1"


class StateProofError(RuntimeError):
    """Raised when storage state cannot be resolved or verified."""


@dataclass(frozen=True)
class StoreFingerprint:
    store_name: str
    fingerprint: str
    manifest_details: dict[str, Any]


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


def verify_store_quiescence(
    pre_proof: FrozenStateProof,
    post_proof: FrozenStateProof,
) -> tuple[bool, str]:
    """Verify that PRE and POST state proofs are byte-for-byte identical."""

    if pre_proof.sqlite_fingerprint != post_proof.sqlite_fingerprint:
        return (
            False,
            f"BLOCKED_BY_RUNTIME_STATE_PROOF: SQLite store mutated during paired execution "
            f"({pre_proof.sqlite_fingerprint} != {post_proof.sqlite_fingerprint})",
        )
    if pre_proof.lancedb_fingerprint != post_proof.lancedb_fingerprint:
        return (
            False,
            f"BLOCKED_BY_RUNTIME_STATE_PROOF: LanceDB vector store mutated during paired execution "
            f"({pre_proof.lancedb_fingerprint} != {post_proof.lancedb_fingerprint})",
        )
    if pre_proof.kuzu_fingerprint != post_proof.kuzu_fingerprint:
        return (
            False,
            f"BLOCKED_BY_RUNTIME_STATE_PROOF: Kùzu graph store mutated during paired execution "
            f"({pre_proof.kuzu_fingerprint} != {post_proof.kuzu_fingerprint})",
        )
    if pre_proof.composite_fingerprint != post_proof.composite_fingerprint:
        return (
            False,
            "BLOCKED_BY_RUNTIME_STATE_PROOF: composite store fingerprint mismatch",
        )

    return True, "QUIESCENT_STATE_VERIFIED"
