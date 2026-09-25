"""Run-ID consistency and deterministic evidence index utilities."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from harness.models import ArtifactReference, EvidenceIndex


class EvidenceIndexError(RuntimeError):
    pass


REUSE_FIELDS = frozenset(
    {
        "path",
        "source_run_id",
        "reuse_reason",
        "expected_sha256",
        "authorization",
    }
)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _confined_path(run_dir: Path, relative: str) -> Path:
    root = run_dir.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise EvidenceIndexError(f"artifact path escapes run directory: {relative}") from exc
    return path


def validate_run_id_consistency(
    run_dir: str | Path,
    run_id: str,
    reuse_authorizations: Iterable[dict[str, str]] = (),
) -> dict[str, object]:
    root = Path(run_dir)
    authorizations: dict[str, dict[str, str]] = {}
    authorization_errors: list[str] = []
    for authorization in reuse_authorizations:
        missing = sorted(REUSE_FIELDS - authorization.keys())
        if missing or any(not authorization.get(field) for field in REUSE_FIELDS):
            authorization_errors.append(
                f"incomplete reuse authorization for {authorization.get('path')!r}: {missing}"
            )
            continue
        authorizations[authorization["path"]] = authorization

    mismatches: list[dict[str, str]] = []
    authorized_reuse: list[dict[str, str]] = []
    for path in sorted(root.rglob("*.json")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        artifact_run_id = payload.get("run_id") if isinstance(payload, dict) else None
        if not artifact_run_id or artifact_run_id == run_id:
            continue
        authorization = authorizations.get(relative)
        valid_authorization = bool(
            authorization
            and authorization["source_run_id"] == artifact_run_id
            and authorization["expected_sha256"] == sha256_file(path)
            and authorization["reuse_reason"].strip()
            and authorization["authorization"].strip()
        )
        if valid_authorization:
            authorized_reuse.append(
                {
                    "path": relative,
                    "source_run_id": artifact_run_id,
                    "expected_sha256": authorization["expected_sha256"],
                    "reuse_reason": authorization["reuse_reason"],
                    "authorization": authorization["authorization"],
                }
            )
        else:
            mismatches.append(
                {
                    "path": relative,
                    "expected_run_id": run_id,
                    "observed_run_id": str(artifact_run_id),
                }
            )

    status = "PASS" if not mismatches and not authorization_errors else "RUN_ID_MISMATCH"
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "status": status,
        "mismatches": mismatches,
        "authorized_reuse": sorted(authorized_reuse, key=lambda item: item["path"]),
        "authorization_errors": authorization_errors,
    }


def build_evidence_index(
    run_dir: str | Path,
    output_path: str | Path,
    records: Iterable[dict[str, Any]],
    *,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, object]:
    root = Path(run_dir)
    inferred_run_id = run_id or root.name
    artifacts: list[ArtifactReference] = []
    seen: set[str] = set()
    for raw_record in records:
        try:
            relative = str(raw_record["path"])
        except KeyError as exc:
            raise EvidenceIndexError("evidence record is missing path") from exc
        if relative in seen:
            raise EvidenceIndexError(f"duplicate evidence index path: {relative}")
        seen.add(relative)
        path = _confined_path(root, relative)
        if not path.is_file():
            raise EvidenceIndexError(f"evidence artifact is missing: {relative}")
        payload = dict(raw_record)
        payload["sha256"] = sha256_file(path)
        try:
            artifacts.append(ArtifactReference.model_validate(payload))
        except ValidationError as exc:
            raise EvidenceIndexError(
                f"invalid evidence metadata for {relative}: {exc}"
            ) from exc

    sorted_artifacts = sorted(artifacts, key=lambda item: item.path)
    entries_for_hash = [
        {"path": art.path, "sha256": art.sha256} for art in sorted_artifacts
    ]
    canonical_bytes = json.dumps(
        entries_for_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    index_hash = hashlib.sha256(canonical_bytes).hexdigest()

    creation_time = created_at or datetime.now(timezone.utc)
    if creation_time.tzinfo is None or creation_time.utcoffset() is None:
        creation_time = creation_time.replace(tzinfo=timezone.utc)

    index_model = EvidenceIndex(
        schema_version="1.0",
        run_id=inferred_run_id,
        created_at_utc=creation_time,
        artifact_count=len(sorted_artifacts),
        artifacts=sorted_artifacts,
        index_hash=index_hash,
    )
    result = index_model.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(
        result, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    Path(output_path).write_text(serialized, encoding="utf-8", newline="\n")
    return result
