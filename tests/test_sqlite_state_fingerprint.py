"""Tests for deterministic SQLite state fingerprinting, WITHOUT ROWID tables, and FTS5 shadow state."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from harness.artifacts import canonical_json_bytes
from harness.state_proof import (
    STATE_PROOF_CONTRACT_VERSION,
    StateProofError,
    capture_frozen_state_proof,
    fingerprint_sqlite,
    verify_store_stability,
)


def _setup_mock_vector_and_graph(tmp_path: Path) -> tuple[Path, Path]:
    lance_dir = tmp_path / "lancedb_data"
    lance_dir.mkdir(parents=True, exist_ok=True)
    (lance_dir / "table.lance").mkdir(parents=True, exist_ok=True)
    (lance_dir / "table.lance" / "1.manifest").write_text("manifest-1", encoding="utf-8")
    (lance_dir / "table.lance" / "data.lance").write_text("data-1", encoding="utf-8")

    kuzu_dir = tmp_path / "kuzu_data"
    kuzu_dir.mkdir(parents=True, exist_ok=True)
    (kuzu_dir / "catalog.kz").write_text("catalog-data", encoding="utf-8")
    (kuzu_dir / "nodes.kz").write_text("nodes-data", encoding="utf-8")
    (kuzu_dir / "edges.kz").write_text("edges-data", encoding="utf-8")
    return lance_dir, kuzu_dir


def test_fingerprint_rowid_table(tmp_path: Path) -> None:
    db_path = tmp_path / "rowid.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t_int_pk (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t_int_pk VALUES (1, 'alice'), (2, 'bob')")
    conn.execute("CREATE TABLE t_text_pk (id TEXT PRIMARY KEY, score REAL)")
    conn.execute("INSERT INTO t_text_pk VALUES ('u1', 99.5), ('u2', 88.0)")
    conn.execute("CREATE TABLE t_no_pk (tag TEXT, count INT)")
    conn.execute("INSERT INTO t_no_pk VALUES ('tagA', 10), ('tagB', 20)")
    conn.commit()
    conn.close()

    fp = fingerprint_sqlite(db_path)
    assert fp.store_name == "sqlite"
    assert fp.fingerprint.startswith("sha256:")
    tables = fp.manifest_details["tables"]
    assert "t_int_pk" in tables and tables["t_int_pk"]["count"] == 2
    assert "t_text_pk" in tables and tables["t_text_pk"]["count"] == 2
    assert "t_no_pk" in tables and tables["t_no_pk"]["count"] == 2
    for tbl in ("t_int_pk", "t_text_pk", "t_no_pk"):
        assert tables[tbl]["content_hash"] is not None


def test_fingerprint_without_rowid_single_pk(tmp_path: Path) -> None:
    db_path = tmp_path / "wor_single.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE documents (doc_id TEXT PRIMARY KEY, body TEXT, score REAL) WITHOUT ROWID"
    )
    conn.execute("INSERT INTO documents VALUES ('doc-1', 'first text', 1.0)")
    conn.execute("INSERT INTO documents VALUES ('doc-2', 'second text', 2.5)")
    conn.commit()
    conn.close()

    fp1 = fingerprint_sqlite(db_path)
    assert fp1.fingerprint.startswith("sha256:")
    assert fp1.manifest_details["tables"]["documents"]["count"] == 2
    assert fp1.manifest_details["tables"]["documents"]["content_hash"] is not None

    # Repeated fingerprint is identical
    fp2 = fingerprint_sqlite(db_path)
    assert fp1.fingerprint == fp2.fingerprint


def test_fingerprint_without_rowid_composite_pk(tmp_path: Path) -> None:
    db_path = tmp_path / "wor_comp.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE edge_index (dst INT, src INT, weight REAL, PRIMARY KEY (src, dst)) WITHOUT ROWID"
    )
    conn.execute("INSERT INTO edge_index VALUES (20, 10, 1.5)")
    conn.execute("INSERT INTO edge_index VALUES (10, 10, 2.0)")
    conn.execute("INSERT INTO edge_index VALUES (5, 20, 3.5)")
    conn.commit()
    conn.close()

    fp = fingerprint_sqlite(db_path)
    assert fp.manifest_details["tables"]["edge_index"]["count"] == 3
    assert fp.manifest_details["tables"]["edge_index"]["content_hash"] is not None


def test_real_fts5_database_and_shadow_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "mesa_fts.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY, entity_name TEXT, type TEXT)")
    conn.execute(
        "CREATE VIRTUAL TABLE nodes_fts USING fts5("
        "entity_name, type, content='nodes', content_rowid='id'"
        ")"
    )
    conn.execute("INSERT INTO nodes VALUES (1, 'Court of Appeals', 'Court')")
    conn.execute("INSERT INTO nodes VALUES (2, 'Securities Commission', 'Regulator')")
    conn.execute(
        "INSERT INTO nodes_fts(rowid, entity_name, type) VALUES (1, 'Court of Appeals', 'Court')"
    )
    conn.execute(
        "INSERT INTO nodes_fts(rowid, entity_name, type) VALUES (2, 'Securities Commission', 'Regulator')"
    )
    conn.commit()
    conn.close()

    fp = fingerprint_sqlite(db_path)
    tables = fp.manifest_details["tables"]

    # All real FTS5 shadow tables must be discovered and fingerprinted without skipping
    expected_shadows = {
        "nodes",
        "nodes_fts",
        "nodes_fts_config",
        "nodes_fts_data",
        "nodes_fts_docsize",
        "nodes_fts_idx",
    }
    assert expected_shadows.issubset(set(tables.keys()))

    for tbl in expected_shadows:
        assert tables[tbl]["count"] >= 0
        assert tables[tbl]["content_hash"] is not None


def test_fts_config_and_idx_mutation_detection(tmp_path: Path) -> None:
    db_path = tmp_path / "fts_mutation.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute(
        "CREATE VIRTUAL TABLE docs_fts USING fts5(title, content='docs', content_rowid='id')"
    )
    conn.execute("INSERT INTO docs VALUES (1, 'statutory interpretation')")
    conn.execute("INSERT INTO docs_fts(rowid, title) VALUES (1, 'statutory interpretation')")
    conn.commit()
    conn.close()

    fp_pre = fingerprint_sqlite(db_path)

    # Mutate FTS config shadow table to a valid version value (4 -> 5)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR REPLACE INTO docs_fts_config VALUES ('version', 5)")
    conn.commit()
    conn.close()

    fp_post_config = fingerprint_sqlite(db_path)
    assert fp_pre.fingerprint != fp_post_config.fingerprint

    # Mutate docs_fts index state by adding and syncing another document
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO docs VALUES (2, 'contract breach')")
    conn.execute("INSERT INTO docs_fts(rowid, title) VALUES (2, 'contract breach')")
    conn.commit()
    conn.close()

    fp_post_doc = fingerprint_sqlite(db_path)
    assert fp_post_config.fingerprint != fp_post_doc.fingerprint


def test_physical_insertion_order_determinism(tmp_path: Path) -> None:
    db1 = tmp_path / "order1.db"
    db2 = tmp_path / "order2.db"

    data_order_1 = [(1, "apple", 10.0), (2, "banana", 20.0), (3, "cherry", 30.0)]
    data_order_2 = [(3, "cherry", 30.0), (1, "apple", 10.0), (2, "banana", 20.0)]

    for path, data in ((db1, data_order_1), (db2, data_order_2)):
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE t_rowid (id INT PRIMARY KEY, name TEXT, val REAL)")
        c.execute("CREATE TABLE t_wor (uuid TEXT PRIMARY KEY, name TEXT, val REAL) WITHOUT ROWID")
        c.execute("CREATE TABLE t_comp (c1 INT, c2 TEXT, c3 REAL, PRIMARY KEY (c2, c1)) WITHOUT ROWID")
        c.execute("CREATE TABLE t_nopk (name TEXT, val REAL)")
        for num, text, flt in data:
            c.execute("INSERT INTO t_rowid VALUES (?, ?, ?)", (num, text, flt))
            c.execute("INSERT INTO t_wor VALUES (?, ?, ?)", (f"u-{num}", text, flt))
            c.execute("INSERT INTO t_comp VALUES (?, ?, ?)", (num, text, flt))
            c.execute("INSERT INTO t_nopk VALUES (?, ?)", (text, flt))
        c.commit()
        c.close()

    fp1 = fingerprint_sqlite(db1)
    fp2 = fingerprint_sqlite(db2)

    assert fp1.fingerprint == fp2.fingerprint, (
        f"fingerprint drifted due to physical insertion order: {fp1.fingerprint} != {fp2.fingerprint}"
    )


def test_blob_determinism_and_unambiguous_types(tmp_path: Path) -> None:
    db_path = tmp_path / "blobs.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE blob_table (id INT PRIMARY KEY, raw_bytes BLOB, text_equiv TEXT)"
    )
    conn.execute(
        "INSERT INTO blob_table VALUES (1, X'000102FF', '{\"\"$blob\"\": \"\"000102ff\"\"}')"
    )
    conn.execute(
        "INSERT INTO blob_table VALUES (2, X'', '')"
    )
    conn.execute(
        "INSERT INTO blob_table VALUES (3, NULL, 'None')"
    )
    conn.commit()
    conn.close()

    fp1 = fingerprint_sqlite(db_path)
    fp2 = fingerprint_sqlite(db_path)
    assert fp1.fingerprint == fp2.fingerprint

    # Ensure BLOB change mutates fingerprint
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE blob_table SET raw_bytes = X'000102FE' WHERE id = 1")
    conn.commit()
    conn.close()

    fp3 = fingerprint_sqlite(db_path)
    assert fp1.fingerprint != fp3.fingerprint


def test_empty_tables_determinism(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE empty_rowid (id INT PRIMARY KEY, val TEXT)")
    conn.execute("CREATE TABLE empty_wor (k TEXT PRIMARY KEY, v INT) WITHOUT ROWID")
    conn.execute("CREATE TABLE empty_nopk (a TEXT, b REAL)")
    conn.execute("CREATE VIRTUAL TABLE empty_fts USING fts5(content)")
    conn.commit()
    conn.close()

    fp1 = fingerprint_sqlite(db_path)
    fp2 = fingerprint_sqlite(db_path)
    assert fp1.fingerprint == fp2.fingerprint

    tables = fp1.manifest_details["tables"]
    assert tables["empty_rowid"]["count"] == 0
    assert tables["empty_wor"]["count"] == 0
    assert tables["empty_nopk"]["count"] == 0
    assert tables["empty_fts"]["count"] == 0


def test_quoted_and_unusual_table_and_column_names(tmp_path: Path) -> None:
    db_path = tmp_path / "quoted.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        'CREATE TABLE "table with space" ("col with space" INT PRIMARY KEY, "order" TEXT)'
    )
    conn.execute('INSERT INTO "table with space" VALUES (1, \'keyword-val\')')
    conn.execute(
        'CREATE TABLE "tbl""quoted""" ("key""col" TEXT PRIMARY KEY, "group" INT) WITHOUT ROWID'
    )
    conn.execute('INSERT INTO "tbl""quoted""" VALUES (\'k1\', 42)')
    conn.commit()
    conn.close()

    fp = fingerprint_sqlite(db_path)
    assert 'table with space' in fp.manifest_details["tables"]
    assert 'tbl"quoted"' in fp.manifest_details["tables"]
    assert fp.manifest_details["tables"]['table with space']["count"] == 1
    assert fp.manifest_details["tables"]['tbl"quoted"']["count"] == 1


def test_state_proof_integration_acceptance_and_rejection(tmp_path: Path) -> None:
    sql_path = tmp_path / "mesa.db"
    conn = sqlite3.connect(sql_path)
    conn.execute("CREATE TABLE assertions (id TEXT PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO assertions VALUES ('a1', 'legal text')")
    conn.execute("CREATE TABLE nodes (id INT PRIMARY KEY, name TEXT)")
    conn.execute("CREATE VIRTUAL TABLE nodes_fts USING fts5(name, content='nodes', content_rowid='id')")
    conn.execute("INSERT INTO nodes VALUES (1, 'entity1')")
    conn.execute("INSERT INTO nodes_fts(rowid, name) VALUES (1, 'entity1')")
    conn.commit()
    conn.close()

    lance_dir, kuzu_dir = _setup_mock_vector_and_graph(tmp_path)

    run_id = "RUN-integration-test"
    pre = capture_frozen_state_proof(
        run_id=run_id, sqlite_path=sql_path, lancedb_dir=lance_dir, kuzu_dir=kuzu_dir
    )
    assert pre.contract_version == STATE_PROOF_CONTRACT_VERSION
    assert pre.sqlite_fingerprint.startswith("sha256:")

    # Unchanged stores -> accepted
    post_unchanged = capture_frozen_state_proof(
        run_id=run_id, sqlite_path=sql_path, lancedb_dir=lance_dir, kuzu_dir=kuzu_dir
    )
    ok, msg, _ = verify_store_stability(pre, post_unchanged)
    assert ok is True
    assert msg == "RETRIEVAL_STATE_UNCHANGED"

    # Mutate FTS state in SQLite -> rejected fail-closed
    conn = sqlite3.connect(sql_path)
    conn.execute("INSERT INTO nodes VALUES (2, 'entity2')")
    conn.execute("INSERT INTO nodes_fts(rowid, name) VALUES (2, 'entity2')")
    conn.commit()
    conn.close()

    post_mutated = capture_frozen_state_proof(
        run_id=run_id, sqlite_path=sql_path, lancedb_dir=lance_dir, kuzu_dir=kuzu_dir
    )
    ok, msg, _ = verify_store_stability(pre, post_mutated)
    assert ok is False
    assert "SQLite" in msg


def test_adversarial_false_pass_checks(tmp_path: Path) -> None:
    db_path = tmp_path / "adversarial.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items (id INT PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO items VALUES (1, 'a'), (2, 'b')")
    conn.commit()
    conn.close()

    fp_base = fingerprint_sqlite(db_path)

    # 1. Row mutation without row count change must change hash
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE items SET val = 'c' WHERE id = 1")
    conn.commit()
    conn.close()
    fp_mutated = fingerprint_sqlite(db_path)
    assert fp_base.fingerprint != fp_mutated.fingerprint

    # 2. Deletion must change hash
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM items WHERE id = 2")
    conn.commit()
    conn.close()
    fp_deleted = fingerprint_sqlite(db_path)
    assert fp_mutated.fingerprint != fp_deleted.fingerprint

    # 3. Schema mutation must change hash
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE INDEX idx_items_val ON items(val)")
    conn.commit()
    conn.close()
    fp_schema = fingerprint_sqlite(db_path)
    assert fp_deleted.fingerprint != fp_schema.fingerprint


def test_explicit_error_context_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "error_context.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sample_tbl (id INT PRIMARY KEY)")
    conn.commit()
    conn.close()

    real_connect = sqlite3.connect

    class MockCursor:
        def __init__(self, cur: Any) -> None:
            self._cur = cur

        def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            if "COUNT(*)" in sql:
                raise sqlite3.OperationalError("simulated count error")
            return self._cur.execute(sql, *args, **kwargs)

        def fetchall(self) -> Any:
            return self._cur.fetchall()

        def fetchone(self) -> Any:
            return self._cur.fetchone()

    class MockConn:
        def __init__(self, c: sqlite3.Connection) -> None:
            self._c = c
            self.isolation_level = None

        def execute(self, *args: Any, **kwargs: Any) -> Any:
            return self._c.execute(*args, **kwargs)

        def rollback(self) -> None:
            self._c.rollback()

        def close(self) -> None:
            self._c.close()

        def cursor(self) -> MockCursor:
            return MockCursor(self._c.cursor())

    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: MockConn(real_connect(*args, **kwargs)))

    with pytest.raises(StateProofError) as exc_info:
        fingerprint_sqlite(db_path)
    err_msg = str(exc_info.value)
    assert "sample_tbl" in err_msg
    assert "count" in err_msg
    assert "simulated count error" in err_msg


def test_determinism_across_process_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "process_restart.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, data BLOB) WITHOUT ROWID")
    conn.execute("INSERT INTO records VALUES ('r1', X'CAFEBABE')")
    conn.execute("CREATE VIRTUAL TABLE fts USING fts5(text)")
    conn.execute("INSERT INTO fts VALUES ('legal clause summary')")
    conn.commit()
    conn.close()

    script = f"""
import sys
from pathlib import Path
from harness.state_proof import fingerprint_sqlite
fp = fingerprint_sqlite({repr(str(db_path))})
print(fp.fingerprint)
"""
    res1 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "111"},
    )
    res2 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "999"},
    )
    fp1 = res1.stdout.strip()
    fp2 = res2.stdout.strip()
    assert fp1 == fp2
    assert fp1.startswith("sha256:")
