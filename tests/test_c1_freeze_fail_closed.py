from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.freeze import (
    FreezeStatus,
    create_contract_freeze,
    verify_contract_freeze,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
RUN_ID = "RUN-20260924T120000Z-c1"


def _create_valid_freeze(tmp_path: Path):
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
    materials: dict[str, list[Path]] = {}
    for cat in categories:
        p = tmp_path / f"{cat}.txt"
        p.write_text(cat, encoding="utf-8")
        materials[cat] = [p]

    repository_shas = {
        "MESA": "a" * 40,
        "MESA_Data": "b" * 40,
        "MESA_E2E_Certification": "c" * 40,
    }
    return create_contract_freeze(
        output_dir=tmp_path,
        run_id=RUN_ID,
        repository_root=tmp_path,
        repository_shas=repository_shas,
        material_paths=materials,
        runtime_identities={"python": "3.13.12"},
        created_at=NOW,
    )


def _write_freeze_and_sidecar(tmp_path: Path, payload: dict) -> tuple[Path, Path]:
    freeze_path = tmp_path / "contract-freeze.json"
    checksum_path = tmp_path / "contract-freeze.SHA256"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    freeze_path.write_text(serialized, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  contract-freeze.json\n", encoding="utf-8")
    return freeze_path, checksum_path


def test_c1_empty_repositories_fail(tmp_path: Path) -> None:
    # Syntactically valid freeze with empty repository_shas
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "created_at_utc": NOW.isoformat(),
        "repository_shas": {},
        "runtime_identities": {"python": "3.13"},
        "materials": [],
    }
    freeze_path, checksum_path = _write_freeze_and_sidecar(tmp_path, payload)
    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is not FreezeStatus.PASS
    assert res.status in {
        FreezeStatus.FREEZE_REPOSITORY_IDENTITY_MISSING,
        FreezeStatus.INVALID_FREEZE,
        FreezeStatus.FREEZE_INVALID,
    }


def test_c1_empty_materials_fail(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "created_at_utc": NOW.isoformat(),
        "repository_shas": {
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
        "runtime_identities": {"python": "3.13"},
        "materials": [],
    }
    freeze_path, checksum_path = _write_freeze_and_sidecar(tmp_path, payload)
    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is not FreezeStatus.PASS
    assert res.status in {
        FreezeStatus.FREEZE_MISSING_REQUIRED_MATERIAL,
        FreezeStatus.INVALID_FREEZE,
        FreezeStatus.FREEZE_INVALID,
    }


def test_c1_missing_one_mandatory_repository_sha_fail(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "created_at_utc": NOW.isoformat(),
        "repository_shas": {
            "MESA": "a" * 40,
            # Missing MESA_Data
            "MESA_E2E_Certification": "c" * 40,
        },
        "runtime_identities": {"python": "3.13"},
        "materials": [
            {
                "category": "config",
                "path": "config.txt",
                "sha256": "e" * 64,
            }
        ],
    }
    freeze_path, checksum_path = _write_freeze_and_sidecar(tmp_path, payload)
    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is not FreezeStatus.PASS
    assert res.status in {
        FreezeStatus.FREEZE_REPOSITORY_IDENTITY_MISSING,
        FreezeStatus.INVALID_FREEZE,
        FreezeStatus.FREEZE_INVALID,
    }


def test_c1_missing_one_mandatory_material_class_fail(tmp_path: Path) -> None:
    # Valid freeze but omit "prompts"
    freeze_path, checksum_path = _create_valid_freeze(tmp_path)
    data = json.loads(freeze_path.read_text(encoding="utf-8"))
    data["materials"] = [m for m in data["materials"] if m["category"] != "prompts"]
    _write_freeze_and_sidecar(tmp_path, data)

    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is not FreezeStatus.PASS
    assert res.status in {
        FreezeStatus.FREEZE_MISSING_REQUIRED_MATERIAL,
        FreezeStatus.INVALID_FREEZE,
        FreezeStatus.FREEZE_INVALID,
    }


def test_c1_wrong_sidecar_hash_fail(tmp_path: Path) -> None:
    freeze_path, checksum_path = _create_valid_freeze(tmp_path)
    checksum_path.write_text("0" * 64 + "  contract-freeze.json\n", encoding="utf-8")

    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is not FreezeStatus.PASS
    assert res.status in {
        FreezeStatus.FREEZE_HASH_MISMATCH,
        FreezeStatus.INVALID_FREEZE,
    }


def test_c1_conflicting_duplicate_material_fail(tmp_path: Path) -> None:
    freeze_path, checksum_path = _create_valid_freeze(tmp_path)
    data = json.loads(freeze_path.read_text(encoding="utf-8"))
    # Add duplicate material with conflicting hash
    data["materials"].append(
        {
            "category": "config",
            "path": "config.txt",
            "sha256": "0" * 64,
        }
    )
    _write_freeze_and_sidecar(tmp_path, data)

    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is not FreezeStatus.PASS


def test_c1_valid_complete_freeze_pass(tmp_path: Path) -> None:
    freeze_path, checksum_path = _create_valid_freeze(tmp_path)
    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is FreezeStatus.PASS
    assert len(res.drift) == 0


def test_c1_freeze_file_modified_after_sidecar_creation_fail(tmp_path: Path) -> None:
    freeze_path, checksum_path = _create_valid_freeze(tmp_path)
    # Modify freeze file without updating sidecar
    with freeze_path.open("a", encoding="utf-8") as f:
        f.write("   \n")

    res = verify_contract_freeze(
        freeze_path,
        checksum_path,
        repository_root=tmp_path,
        current_repository_shas={
            "MESA": "a" * 40,
            "MESA_Data": "b" * 40,
            "MESA_E2E_Certification": "c" * 40,
        },
    )
    assert res.status is not FreezeStatus.PASS
    assert res.status in {
        FreezeStatus.FREEZE_HASH_MISMATCH,
        FreezeStatus.INVALID_FREEZE,
    }
