"""Contract-freeze generation and byte-exact mutation verification."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


MANDATORY_MATERIAL_CATEGORIES = frozenset(
    {
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
    }
)
MANDATORY_REPOSITORIES = frozenset(
    {"MESA", "MESA_Data", "MESA_E2E_Certification"}
)
HEX_DIGEST = re.compile(r"^[0-9a-f]+$")


class FreezeError(RuntimeError):
    pass


class FreezeStatus(str, Enum):
    PASS = "PASS"
    MISSING_FREEZE = "MISSING_FREEZE"
    INVALID_FREEZE = "INVALID_FREEZE"
    INVALIDATED_CODE_CHANGE = "INVALIDATED_CODE_CHANGE"


class FreezeVerification:
    def __init__(self, status: FreezeStatus, drift: list[str] | None = None):
        self.status = status
        self.drift = drift or []

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status.value, "drift": list(self.drift)}


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise FreezeError(f"freeze material escapes repository root: {path}") from exc


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FreezeError("freeze timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def create_contract_freeze(
    *,
    output_dir: str | Path,
    run_id: str,
    repository_root: str | Path,
    repository_shas: dict[str, str],
    material_paths: dict[str, list[Path]],
    runtime_identities: dict[str, Any],
    created_at: datetime | None = None,
) -> tuple[Path, Path]:
    if not run_id:
        raise FreezeError("run_id must be non-empty")
    missing_categories = sorted(
        category
        for category in MANDATORY_MATERIAL_CATEGORIES
        if not material_paths.get(category)
    )
    if missing_categories:
        raise FreezeError(
            f"missing mandatory freeze categories: {missing_categories}"
        )
    missing_repositories = sorted(MANDATORY_REPOSITORIES - repository_shas.keys())
    if missing_repositories:
        raise FreezeError(f"missing repository SHAs: {missing_repositories}")
    for name, sha in repository_shas.items():
        if len(sha) not in {40, 64} or HEX_DIGEST.fullmatch(sha) is None:
            raise FreezeError(f"invalid repository SHA for {name}: {sha!r}")
    if not runtime_identities:
        raise FreezeError("runtime identities must not be empty")

    root = Path(repository_root)
    materials: list[dict[str, str]] = []
    for category in sorted(material_paths):
        for path in sorted(material_paths[category], key=lambda item: item.as_posix()):
            if not path.is_file():
                raise FreezeError(f"freeze material is missing: {path}")
            materials.append(
                {
                    "category": category,
                    "path": _relative_path(path, root),
                    "sha256": _sha256(path),
                }
            )

    payload = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at_utc": _utc_text(created_at or datetime.now(timezone.utc)),
        "repository_shas": dict(sorted(repository_shas.items())),
        "runtime_identities": runtime_identities,
        "materials": sorted(
            materials, key=lambda item: (item["category"], item["path"])
        ),
    }
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    freeze_path = destination / "contract-freeze.json"
    checksum_path = destination / "contract-freeze.SHA256"
    serialized = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    freeze_path.write_text(serialized, encoding="utf-8", newline="\n")
    digest = _sha256(freeze_path)
    checksum_path.write_text(
        f"{digest}  contract-freeze.json\n", encoding="utf-8", newline="\n"
    )
    return freeze_path, checksum_path


def verify_contract_freeze(
    freeze_path: str | Path,
    checksum_path: str | Path,
    *,
    repository_root: str | Path,
    current_repository_shas: dict[str, str],
) -> FreezeVerification:
    freeze = Path(freeze_path)
    checksum = Path(checksum_path)
    if not freeze.is_file() or not checksum.is_file():
        return FreezeVerification(
            FreezeStatus.MISSING_FREEZE,
            ["contract-freeze.json or contract-freeze.SHA256 is missing"],
        )
    try:
        checksum_parts = checksum.read_text(encoding="utf-8").strip().split()
        if (
            len(checksum_parts) != 2
            or checksum_parts[1] != freeze.name
            or checksum_parts[0] != _sha256(freeze)
        ):
            return FreezeVerification(
                FreezeStatus.INVALID_FREEZE,
                ["contract freeze checksum mismatch"],
            )
        payload = json.loads(freeze.read_text(encoding="utf-8"))
        frozen_repositories = payload["repository_shas"]
        materials = payload["materials"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return FreezeVerification(FreezeStatus.INVALID_FREEZE, [str(exc)])

    drift: list[str] = []
    for name, frozen_sha in sorted(frozen_repositories.items()):
        current_sha = current_repository_shas.get(name)
        if current_sha != frozen_sha:
            drift.append(
                f"repository SHA drift for {name}: {frozen_sha} -> {current_sha}"
            )

    root = Path(repository_root).resolve()
    for item in materials:
        try:
            relative = Path(item["path"])
            path = (root / relative).resolve()
            path.relative_to(root)
            expected_sha = item["sha256"]
        except (KeyError, TypeError, ValueError) as exc:
            return FreezeVerification(FreezeStatus.INVALID_FREEZE, [str(exc)])
        if not path.is_file():
            drift.append(f"missing frozen material: {relative.as_posix()}")
            continue
        observed = _sha256(path)
        if observed != expected_sha:
            drift.append(
                f"material SHA drift for {relative.as_posix()}: "
                f"{expected_sha} -> {observed}"
            )

    if drift:
        return FreezeVerification(FreezeStatus.INVALIDATED_CODE_CHANGE, drift)
    return FreezeVerification(FreezeStatus.PASS)
