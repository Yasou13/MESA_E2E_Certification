from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.evidence import (
    EvidenceIndexError,
    build_evidence_index,
)
from harness.finalizer import (
    REQUIRED_RELEASE_FILES,
    ReleaseFinalizationError,
    finalize_release,
)
from harness.models import EvidenceIndex

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
RUN_ID = "RUN-20260924T120000Z-c5"


def _make_release_sources(tmp_path: Path, evidence_index_path: Path) -> dict[str, Path]:
    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for name in REQUIRED_RELEASE_FILES:
        path = source_dir / name
        if name == "final-report.md":
            path.write_text(f"# Final report\n\nRun: {RUN_ID}\n", encoding="utf-8")
        elif name == "evidence-index.json":
            result[name] = evidence_index_path
            continue
        else:
            payload: dict[str, object] = {
                "schema_version": "1.0",
                "run_id": RUN_ID,
                "status": "PASS",
            }
            if name == "gate-results.json":
                payload.update(
                    {
                        "final_verdict": "PROFILE_B_PASS_NATIVE",
                        "mandatory_gate_ids": ["B10"],
                        "gates": [
                            {
                                "gate_id": "B10",
                                "hard": True,
                                "status": "PASS",
                                "requirements": {
                                    "answerable_mrr": {"operator": "gte", "value": 0.7}
                                },
                                "observed": {"answerable_mrr": 0.85},
                            }
                        ],
                    }
                )
            elif name == "contract-freeze.json":
                categories = (
                    "harness_source",
                    "scorer_source",
                    "config",
                    "ground_truth",
                    "qrels",
                    "normalization",
                    "identity_map",
                    "prompts",
                    "thresholds",
                    "runtime_identity",
                )
                payload.update(
                    {
                        "repository_shas": {
                            "MESA": "a" * 40,
                            "MESA_Data": "b" * 40,
                            "MESA_E2E_Certification": "c" * 40,
                        },
                        "materials": [
                            {"category": cat, "path": f"{cat}.txt", "sha256": "0" * 64}
                            for cat in categories
                        ],
                    }
                )
            elif name == "run_manifest.json":
                payload.update(
                    {
                        "status": "PASS_NATIVE",
                        "lifecycle_valid": True,
                    }
                )
            path.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )
        result[name] = path
    return result


def _produce_real_index(run_dir: Path, output_path: Path, run_id: str = RUN_ID) -> Path:
    f1 = run_dir / "art1.json"
    f2 = run_dir / "art2.json"
    f1.write_text('{"item": 1}\n', encoding="utf-8")
    f2.write_text('{"item": 2}\n', encoding="utf-8")
    build_evidence_index(
        run_dir=run_dir,
        output_path=output_path,
        records=[
            {
                "path": "art1.json",
                "producer": "harness",
                "phase": "execution",
                "timestamp_utc": NOW,
                "source_run_id": run_id,
                "immutable": True,
                "sealed": True,
                "artifact_type": "evidence",
            },
            {
                "path": "art2.json",
                "producer": "harness",
                "phase": "execution",
                "timestamp_utc": NOW,
                "source_run_id": run_id,
                "immutable": True,
                "sealed": True,
                "artifact_type": "evidence",
            },
        ],
        run_id=run_id,
        created_at=NOW,
    )
    return output_path


def test_c5_01_real_producer_accepted_by_real_finalizer(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    index_path = run_dir / "evidence-index.json"
    _produce_real_index(run_dir, index_path)

    sources = _make_release_sources(tmp_path, index_path)
    gate_path = sources["gate-results.json"]
    gate_payload = json.loads(gate_path.read_text())
    gate_payload["final_verdict"] = "PROFILE_B_BLOCKED_PRECONDITION"
    gate_path.write_text(json.dumps(gate_payload))
    dest = finalize_release(
        run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
    )
    assert dest.exists()
    assert (dest / "evidence-index.json").is_file()


def test_c5_02_wrong_run_id_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / "RUN-OTHER"
    run_dir.mkdir(parents=True, exist_ok=True)
    index_path = run_dir / "evidence-index.json"
    _produce_real_index(run_dir, index_path, run_id="RUN-OTHER")

    sources = _make_release_sources(tmp_path, index_path)
    with pytest.raises(ReleaseFinalizationError, match="RUN_ID mismatch"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c5_03_missing_run_id_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    index_path = run_dir / "evidence-index.json"
    _produce_real_index(run_dir, index_path)

    # Strip run_id
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload.pop("run_id", None)
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    sources = _make_release_sources(tmp_path, index_path)
    with pytest.raises(ReleaseFinalizationError):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c5_04_duplicate_conflicting_artifact_path_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    f1 = run_dir / "dup.json"
    f1.write_text('{"item": 1}\n', encoding="utf-8")
    index_path = run_dir / "evidence-index.json"

    with pytest.raises(EvidenceIndexError, match="duplicate"):
        build_evidence_index(
            run_dir=run_dir,
            output_path=index_path,
            records=[
                {
                    "path": "dup.json",
                    "producer": "p1",
                    "phase": "e1",
                    "timestamp_utc": NOW,
                    "source_run_id": RUN_ID,
                    "immutable": True,
                    "sealed": True,
                },
                {
                    "path": "dup.json",
                    "producer": "p2",
                    "phase": "e2",
                    "timestamp_utc": NOW,
                    "source_run_id": RUN_ID,
                    "immutable": True,
                    "sealed": True,
                },
            ],
            run_id=RUN_ID,
        )


def test_c5_05_wrong_artifact_hash_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    index_path = run_dir / "evidence-index.json"
    _produce_real_index(run_dir, index_path)

    # Tamper one artifact hash in index
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["sha256"] = "0" * 64
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    sources = _make_release_sources(tmp_path, index_path)
    with pytest.raises(ReleaseFinalizationError, match="hash|integrity"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c5_06_extra_unknown_field_rejected_by_schema(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "created_at_utc": NOW.isoformat(),
        "artifact_count": 0,
        "artifacts": [],
        "unknown_extra_field": "forbidden",
    }
    with pytest.raises(ValidationError):
        EvidenceIndex.model_validate(payload)


def test_c5_07_deterministic_index_generation(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    out1 = run_dir / "idx1.json"
    out2 = run_dir / "idx2.json"
    _produce_real_index(run_dir, out1)
    _produce_real_index(run_dir, out2)
    assert out1.read_bytes() == out2.read_bytes()


def test_c5_08_reused_artifact_accepted_only_when_authorized(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    index_path = run_dir / "evidence-index.json"
    f1 = run_dir / "reused.json"
    f1.write_text('{"reused": true}\n', encoding="utf-8")

    # Reused artifact without authorization/permit in release finalizer
    build_evidence_index(
        run_dir=run_dir,
        output_path=index_path,
        records=[
            {
                "path": "reused.json",
                "producer": "prior_run",
                "phase": "gt",
                "timestamp_utc": NOW,
                "source_run_id": "RUN-HISTORICAL-PRIOR",
                "immutable": True,
                "sealed": True,
            }
        ],
        run_id=RUN_ID,
    )

    sources = _make_release_sources(tmp_path, index_path)
    # Without explicit policy or authorization, undeclared foreign artifact fails
    with pytest.raises(ReleaseFinalizationError, match="source_run_id|reused|unauthorized|foreign"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )
