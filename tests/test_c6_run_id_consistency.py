import gzip
import json
from pathlib import Path

from harness.evidence import validate_run_id_consistency


RUN_ID = "RUN-20260925T120000Z-test01"


def test_valid_jsonl_with_uniform_run_id_passes(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    
    # Valid json file
    (run_dir / "verdict.json").write_text(
        json.dumps({"run_id": RUN_ID, "verdict": "PASS"}), encoding="utf-8"
    )
    # Valid jsonl file with uniform run_id
    telemetry_path = run_dir / "telemetry.jsonl"
    lines = [
        json.dumps({"step": i, "run_id": RUN_ID, "action": f"step_{i}"})
        for i in range(10)
    ]
    telemetry_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "PASS"
    assert len(report["mismatches"]) == 0


def test_jsonl_with_one_mismatched_record_among_many_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    telemetry_path = run_dir / "telemetry.jsonl"
    lines = [
        json.dumps({"step": i, "run_id": RUN_ID, "action": "ok"})
        for i in range(100)
    ]
    # Insert 1 corrupted/foreign row at index 42
    lines[42] = json.dumps({"step": 42, "run_id": "RUN-FOREIGN-ATTACK", "action": "sneaky"})
    telemetry_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"
    assert any("telemetry.jsonl" in m["path"] and m["observed_run_id"] == "RUN-FOREIGN-ATTACK" for m in report["mismatches"])


def test_corrupted_line_in_jsonl_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    telemetry_path = run_dir / "telemetry.jsonl"
    telemetry_path.write_text(
        json.dumps({"step": 1, "run_id": RUN_ID}) + "\n{NOT_VALID_JSON}\n",
        encoding="utf-8"
    )

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"
    assert len(report.get("parse_errors", [])) > 0


def test_allowed_non_run_id_artifact_passes(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    # Valid JSON with run_id
    (run_dir / "verdict.json").write_text(
        json.dumps({"run_id": RUN_ID, "verdict": "PASS"}), encoding="utf-8"
    )
    # Allowed non-run-id artifacts
    (run_dir / "bootstrap-layout.json").write_text(
        json.dumps({"canonical_root": "/tmp/test"}), encoding="utf-8"
    )
    (run_dir / "ground-truth-test.jsonl").write_text(
        json.dumps({"query_id": "Q1", "question": "test?"}) + "\n",
        encoding="utf-8"
    )

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "PASS"


def test_unauthorized_foreign_run_id_in_json_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    (run_dir / "report.json").write_text(
        json.dumps({"run_id": "RUN-FOREIGN-999"}), encoding="utf-8"
    )

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"
    assert any(m["path"] == "report.json" for m in report["mismatches"])


def test_nested_metadata_foreign_run_id_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    (run_dir / "nested.json").write_text(
        json.dumps({"metadata": {"run_id": "RUN-FOREIGN-NESTED"}}), encoding="utf-8"
    )

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"
    assert any("nested.json" in m["path"] for m in report["mismatches"])


def test_empty_mandatory_structured_file_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    (run_dir / "empty.json").write_text("", encoding="utf-8")

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"


def test_unallowed_non_run_id_artifact_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    (run_dir / "unexpected-audit.json").write_text(
        json.dumps({"untracked_field": 123}), encoding="utf-8"
    )

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"


def test_compressed_jsonl_with_mismatch_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()

    gz_path = run_dir / "telemetry.jsonl.gz"
    payload = json.dumps({"step": 1, "run_id": "RUN-FOREIGN-GZ"}).encode("utf-8") + b"\n"
    gz_path.write_bytes(gzip.compress(payload))

    report = validate_run_id_consistency(run_dir, RUN_ID)
    assert report["status"] == "RUN_ID_MISMATCH"
