from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.evidence import (
    EvidenceIndexError,
    build_evidence_index,
    validate_run_id_consistency,
)
from harness.freeze import (
    FreezeError,
    FreezeStatus,
    create_contract_freeze,
    verify_contract_freeze,
)
from harness.lifecycle import InvalidTransitionError, RunLifecycle
from harness.models import RunStatus


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
RUN_ID = "RUN-20260924T120000Z-test"


def test_lifecycle_accepts_only_declared_transitions() -> None:
    lifecycle = RunLifecycle(RUN_ID)
    with pytest.raises(InvalidTransitionError):
        lifecycle.transition(RunStatus.TEST_RUNNING, at=NOW)

    for status in (
        RunStatus.BOOTSTRAPPED,
        RunStatus.HARNESS_READY,
        RunStatus.GT_FROZEN,
        RunStatus.CONTRACT_FROZEN,
        RunStatus.TEST_RUNNING,
        RunStatus.TEST_COMPLETED,
        RunStatus.FINALIZING,
        RunStatus.PASS_NATIVE,
    ):
        lifecycle.transition(status, at=NOW)

    assert lifecycle.status is RunStatus.PASS_NATIVE
    with pytest.raises(InvalidTransitionError):
        lifecycle.transition(RunStatus.FAIL, at=NOW)


def _freeze_materials(root: Path) -> dict[str, list[Path]]:
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
    result: dict[str, list[Path]] = {}
    for category in categories:
        path = root / f"{category}.txt"
        path.write_text(category, encoding="utf-8")
        result[category] = [path]
    return result


def test_contract_freeze_detects_material_and_repo_sha_drift(tmp_path: Path) -> None:
    materials = _freeze_materials(tmp_path)
    freeze_path, checksum_path = create_contract_freeze(
        output_dir=tmp_path,
        run_id=RUN_ID,
        repository_root=tmp_path,
        repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
        material_paths=materials,
        runtime_identities={"python": "3.13.12", "model": "frozen-model"},
        created_at=NOW,
    )

    valid = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert valid.status is FreezeStatus.PASS

    materials["config"][0].write_text("mutated", encoding="utf-8")
    drift = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "d" * 40,
        },
    )
    assert drift.status is FreezeStatus.INVALIDATED_CODE_CHANGE
    assert any("config.txt" in item for item in drift.drift)
    assert any("MESA_E2E_Certification" in item for item in drift.drift)


def test_contract_freeze_requires_all_material_categories(tmp_path: Path) -> None:
    with pytest.raises(FreezeError, match="missing mandatory freeze categories"):
        create_contract_freeze(
            output_dir=tmp_path,
            run_id=RUN_ID,
            repository_root=tmp_path,
            repository_shas={"MESA_E2E_Certification": "a" * 40},
            material_paths={"config": []},
            runtime_identities={},
            created_at=NOW,
        )

    missing = verify_contract_freeze(
        tmp_path / "missing.json",
        tmp_path / "missing.SHA256",
        repository_root=tmp_path,
        current_repository_shas={},
    )
    assert missing.status is FreezeStatus.MISSING_FREEZE


def test_run_id_mismatch_fails_without_complete_reuse_authorization(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    artifact = run_dir / "control.json"
    artifact.write_text(
        json.dumps({"run_id": "RUN-OLDER", "value": 1}), encoding="utf-8"
    )

    mismatch = validate_run_id_consistency(run_dir, RUN_ID)
    assert mismatch["status"] == "RUN_ID_MISMATCH"

    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    authorized = validate_run_id_consistency(
        run_dir,
        RUN_ID,
        reuse_authorizations=[
            {
                "path": "control.json",
                "source_run_id": "RUN-OLDER",
                "reuse_reason": "immutable corpus manifest reuse",
                "expected_sha256": digest,
                "authorization": "HUMAN-APPROVAL-1",
            }
        ],
    )
    assert authorized["status"] == "PASS"


def test_evidence_index_is_hashed_sorted_and_path_confined(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    (run_dir / "b.json").write_text("{}", encoding="utf-8")
    (run_dir / "a.json").write_text("{}", encoding="utf-8")
    output = run_dir / "evidence-index.json"

    payload = build_evidence_index(
        run_dir,
        output,
        [
            {
                "path": "b.json",
                "producer": "test",
                "phase": "E4",
                "timestamp_utc": NOW,
                "source_run_id": RUN_ID,
                "immutable": True,
                "sealed": False,
            },
            {
                "path": "a.json",
                "producer": "test",
                "phase": "E4",
                "timestamp_utc": NOW,
                "source_run_id": RUN_ID,
                "immutable": True,
                "sealed": True,
            },
        ],
    )

    assert [item["path"] for item in payload["artifacts"]] == ["a.json", "b.json"]
    assert all(len(item["sha256"]) == 64 for item in payload["artifacts"])
    with pytest.raises(EvidenceIndexError):
        build_evidence_index(
            run_dir,
            output,
            [
                {
                    "path": "../outside.json",
                    "producer": "test",
                    "phase": "E4",
                    "timestamp_utc": NOW,
                    "source_run_id": RUN_ID,
                    "immutable": True,
                    "sealed": False,
                }
            ],
        )
