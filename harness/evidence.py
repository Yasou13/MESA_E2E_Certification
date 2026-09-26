"""Run-ID consistency and deterministic evidence index utilities."""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import gzip
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


DEFAULT_ALLOWED_NON_RUN_ID_PATTERNS = frozenset(
    {
        "bootstrap-layout.json",
        "ground-truth*.jsonl",
        "qrels*.jsonl",
        "identity_map*.jsonl",
        "retrieval-results-raw*",
        "decision_log.jsonl",
    }
)


def validate_run_id_consistency(
    run_dir: str | Path,
    run_id: str,
    reuse_authorizations: Iterable[dict[str, str]] = (),
    *,
    allowed_non_run_id_patterns: Iterable[str] | None = None,
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

    effective_allowed = set(DEFAULT_ALLOWED_NON_RUN_ID_PATTERNS)
    if allowed_non_run_id_patterns:
        effective_allowed.update(allowed_non_run_id_patterns)

    mismatches: list[dict[str, str]] = []
    authorized_reuse: list[dict[str, str]] = []
    parse_errors: list[str] = []

    structured_candidates: list[Path] = []
    for ext in ("*.json", "*.jsonl", "*.json.gz", "*.jsonl.gz"):
        structured_candidates.extend(root.rglob(ext))

    structured_files = sorted(
        set(p for p in structured_candidates if p.is_file() and not p.is_symlink()),
        key=lambda p: p.relative_to(root).as_posix(),
    )

    for path in structured_files:
        relative = path.relative_to(root).as_posix()
        name = path.name

        def is_allowlisted() -> bool:
            return any(
                fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(relative, pat)
                for pat in effective_allowed
            )

        try:
            if path.stat().st_size == 0:
                parse_errors.append(f"empty structured artifact: {relative}")
                continue
        except OSError as exc:
            parse_errors.append(f"cannot stat structured artifact {relative}: {exc}")
            continue

        is_gz = name.endswith(".gz")
        is_jsonl = name.endswith(".jsonl") or name.endswith(".jsonl.gz")

        try:
            raw_bytes = path.read_bytes()
            if is_gz:
                data_bytes = gzip.decompress(raw_bytes)
            else:
                data_bytes = raw_bytes
            content_str = data_bytes.decode("utf-8")
        except Exception as exc:
            parse_errors.append(f"cannot read/decompress {relative}: {exc}")
            continue

        def record_mismatch(observed: str, subpath: str = relative) -> None:
            authorization = authorizations.get(relative)
            valid_authorization = bool(
                authorization
                and authorization["source_run_id"] == observed
                and authorization["expected_sha256"] == sha256_file(path)
                and authorization["reuse_reason"].strip()
                and authorization["authorization"].strip()
            )
            if valid_authorization:
                if not any(item["path"] == relative for item in authorized_reuse):
                    authorized_reuse.append(
                        {
                            "path": relative,
                            "source_run_id": observed,
                            "expected_sha256": authorization["expected_sha256"],
                            "reuse_reason": authorization["reuse_reason"],
                            "authorization": authorization["authorization"],
                        }
                    )
            else:
                mismatches.append(
                    {
                        "path": subpath,
                        "expected_run_id": run_id,
                        "observed_run_id": observed,
                    }
                )

        if is_jsonl:
            lines = content_str.splitlines()
            has_records = False
            has_run_id = False
            for line_idx, line in enumerate(lines, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                has_records = True
                try:
                    record = json.loads(stripped)
                except Exception as exc:
                    parse_errors.append(
                        f"unparseable jsonl record at {relative}:{line_idx}: {exc}"
                    )
                    continue

                if isinstance(record, dict):
                    rec_run_id = record.get("run_id") or (
                        record.get("metadata", {}).get("run_id")
                        if isinstance(record.get("metadata"), dict)
                        else None
                    )
                    if rec_run_id is not None:
                        has_run_id = True
                        if str(rec_run_id) != run_id:
                            record_mismatch(str(rec_run_id), subpath=f"{relative}:{line_idx}")
                    elif not is_allowlisted():
                        record_mismatch("MISSING", subpath=f"{relative}:{line_idx}")
                    meta_id = record.get("metadata", {}).get("run_id") if isinstance(record.get("metadata"), dict) else None
                    if meta_id is not None and str(meta_id) != run_id:
                        record_mismatch(str(meta_id), subpath=f"{relative}:{line_idx}.metadata")
                elif not is_allowlisted():
                    record_mismatch("MISSING", subpath=f"{relative}:{line_idx}")

            if not has_records and not is_allowlisted():
                parse_errors.append(f"empty jsonl content: {relative}")
            elif not has_run_id and not is_allowlisted():
                mismatches.append(
                    {
                        "path": relative,
                        "expected_run_id": run_id,
                        "observed_run_id": "MISSING",
                    }
                )

        else:
            try:
                payload = json.loads(content_str)
            except Exception as exc:
                parse_errors.append(f"unparseable json artifact {relative}: {exc}")
                continue

            observed_run_ids: list[str] = []
            if isinstance(payload, dict):
                if "run_id" in payload and payload["run_id"] is not None:
                    observed_run_ids.append(str(payload["run_id"]))
                meta = payload.get("metadata")
                if isinstance(meta, dict) and "run_id" in meta and meta["run_id"] is not None:
                    observed_run_ids.append(str(meta["run_id"]))
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and "run_id" in item and item["run_id"] is not None:
                        observed_run_ids.append(str(item["run_id"]))
                    elif not is_allowlisted():
                        observed_run_ids.append("MISSING")

            if not observed_run_ids:
                if not is_allowlisted():
                    mismatches.append(
                        {
                            "path": relative,
                            "expected_run_id": run_id,
                            "observed_run_id": "MISSING",
                        }
                    )
            else:
                for obs in observed_run_ids:
                    if obs != run_id:
                        record_mismatch(obs, subpath=relative)

    status = (
        "PASS"
        if not mismatches and not authorization_errors and not parse_errors
        else "RUN_ID_MISMATCH"
    )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "status": status,
        "mismatches": mismatches,
        "authorized_reuse": sorted(authorized_reuse, key=lambda item: item["path"]),
        "authorization_errors": authorization_errors,
        "parse_errors": parse_errors,
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
