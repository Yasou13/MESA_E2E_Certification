"""Atomic, fail-closed construction and verification of release bundles."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping

from harness.models import VerdictStatus


REQUIRED_RELEASE_FILES = {
    "answer-summary.json",
    "contract-freeze.json",
    "decision-summary.json",
    "determinism-manifest.json",
    "evidence-index.json",
    "final-report.md",
    "frozen-identities.json",
    "gate-results.json",
    "graph-summary.json",
    "health-post-test.json",
    "health-pre-test.json",
    "identity-map-summary.json",
    "repair-summary.json",
    "resource-provider-summary.json",
    "retrieval-summary.json",
    "run_manifest.json",
    "scorer-canary-results.json",
}

_REQUIRED_PASS_ARTIFACTS = {
    "health-post-test.json",
    "health-pre-test.json",
    "resource-provider-summary.json",
    "scorer-canary-results.json",
}
_SENSITIVE_FIELDS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer_token",
    "exact_model_visible_context",
    "gold_evidence_ids",
    "password",
    "qrel",
    "qrels",
    "raw_response",
    "refresh_token",
    "required_facts",
    "secret",
    "system_prompt",
    "user_prompt",
}
_SECRET_BYTE_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class ReleaseFinalizationError(RuntimeError):
    """Raised before an incomplete or unsafe bundle can be promoted."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized_field(name: object) -> str:
    return str(name).casefold().replace("-", "_")


def _find_sensitive_field(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            field = _normalized_field(key)
            nested_path = f"{path}.{key}"
            if field in _SENSITIVE_FIELDS:
                return nested_path
            found = _find_sensitive_field(nested, nested_path)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _find_sensitive_field(nested, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _validate_no_secret_bytes(name: str, content: bytes) -> None:
    for pattern in _SECRET_BYTE_PATTERNS:
        if pattern.search(content):
            raise ReleaseFinalizationError(
                f"high-confidence secret pattern found in {name}"
            )


def _load_and_validate_source(
    *, name: str, source: Path, run_id: str
) -> bytes:
    if source.is_symlink():
        raise ReleaseFinalizationError(f"release source must not be a symlink: {name}")
    if not source.is_file():
        raise ReleaseFinalizationError(f"release source is not a file: {name}")
    if source.name != name:
        raise ReleaseFinalizationError(
            f"release source filename mismatch for {name}: {source.name}"
        )

    content = source.read_bytes()
    if not content:
        raise ReleaseFinalizationError(f"release source is empty: {name}")
    _validate_no_secret_bytes(name, content)

    if name == "final-report.md":
        try:
            report = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseFinalizationError("final-report.md is not UTF-8") from exc
        if run_id not in report:
            raise ReleaseFinalizationError(
                "final-report.md does not identify the final RUN_ID"
            )
        return content

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseFinalizationError(f"invalid JSON release source: {name}") from exc
    if not isinstance(payload, dict):
        raise ReleaseFinalizationError(f"JSON release source must be an object: {name}")
    if not isinstance(payload.get("schema_version"), str):
        raise ReleaseFinalizationError(f"schema_version missing from {name}")
    if payload.get("run_id") != run_id:
        raise ReleaseFinalizationError(f"RUN_ID mismatch in {name}")
    sensitive_path = _find_sensitive_field(payload)
    if sensitive_path is not None:
        raise ReleaseFinalizationError(
            f"sensitive field is forbidden in {name}: {sensitive_path}"
        )
    return content


def _validate_pass_claim(payloads: Mapping[str, dict[str, Any]]) -> None:
    gate_results = payloads["gate-results.json"]
    verdict = gate_results.get("final_verdict")
    allowed = {status.value for status in VerdictStatus}
    if verdict not in allowed:
        raise ReleaseFinalizationError("gate-results.json has an invalid final verdict")
    if not isinstance(gate_results.get("gates"), list) or not gate_results["gates"]:
        raise ReleaseFinalizationError("gate-results.json has no gate results")
    if verdict != VerdictStatus.PROFILE_B_PASS_NATIVE.value:
        return
    for name in sorted(_REQUIRED_PASS_ARTIFACTS):
        if payloads[name].get("status") != "PASS":
            raise ReleaseFinalizationError(
                f"PASS release requires {name} status PASS"
            )


def finalize_release(
    *, run_id: str, sources: Mapping[str, str | Path], release_root: str | Path
) -> Path:
    """Validate, checksum, and atomically promote a sanitized release bundle."""

    if _SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ReleaseFinalizationError("unsafe RUN_ID")
    supplied = set(sources)
    missing = sorted(REQUIRED_RELEASE_FILES - supplied)
    extra = sorted(supplied - REQUIRED_RELEASE_FILES)
    if missing:
        raise ReleaseFinalizationError(f"missing mandatory release artifacts: {missing}")
    if extra:
        raise ReleaseFinalizationError(f"unexpected release artifacts: {extra}")

    destination_root = Path(release_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / run_id
    if destination.exists() or destination.is_symlink():
        raise ReleaseFinalizationError(f"release destination already exists: {run_id}")

    validated: dict[str, bytes] = {}
    json_payloads: dict[str, dict[str, Any]] = {}
    for name in sorted(REQUIRED_RELEASE_FILES):
        content = _load_and_validate_source(
            name=name, source=Path(sources[name]), run_id=run_id
        )
        validated[name] = content
        if name.endswith(".json"):
            json_payloads[name] = json.loads(content)
    _validate_pass_claim(json_payloads)

    staging_path: Path | None = None
    try:
        staging_path = Path(
            tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=destination_root)
        )
        checksum_lines: list[str] = []
        for name in sorted(REQUIRED_RELEASE_FILES):
            content = validated[name]
            output = staging_path / name
            output.write_bytes(content)
            checksum_lines.append(f"{_sha256(content)}  {name}\n")
        (staging_path / "SHA256SUMS.txt").write_text(
            "".join(checksum_lines), encoding="utf-8", newline="\n"
        )
        os.replace(staging_path, destination)
        staging_path = None
    except OSError as exc:
        raise ReleaseFinalizationError(f"atomic release promotion failed: {exc}") from exc
    finally:
        if staging_path is not None and staging_path.exists():
            shutil.rmtree(staging_path)

    verification = verify_release_bundle(destination)
    if verification["status"] != "PASS":
        raise ReleaseFinalizationError(
            f"promoted release failed verification: {verification['errors']}"
        )
    return destination


def verify_release_bundle(release_dir: str | Path) -> dict[str, object]:
    """Verify an existing bundle without mutating it."""

    directory = Path(release_dir)
    errors: list[str] = []
    expected = REQUIRED_RELEASE_FILES | {"SHA256SUMS.txt"}
    if not directory.is_dir() or directory.is_symlink():
        return {"status": "FAIL", "errors": ["release directory is missing or unsafe"]}

    actual = {entry.name for entry in directory.iterdir()}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            errors.append(f"missing files: {missing}")
        if extra:
            errors.append(f"unexpected files: {extra}")

    checksum_path = directory / "SHA256SUMS.txt"
    checksum_entries: dict[str, str] = {}
    if checksum_path.is_file() and not checksum_path.is_symlink():
        for line_number, line in enumerate(
            checksum_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
            if match is None:
                errors.append(f"invalid checksum line {line_number}")
                continue
            digest, name = match.groups()
            if name in checksum_entries:
                errors.append(f"duplicate checksum entry: {name}")
            checksum_entries[name] = digest
    else:
        errors.append("SHA256SUMS.txt is missing or unsafe")

    if set(checksum_entries) != REQUIRED_RELEASE_FILES:
        errors.append("checksum manifest does not exactly cover required files")
    for name, expected_digest in checksum_entries.items():
        path = directory / name
        if not path.is_file() or path.is_symlink():
            errors.append(f"checksummed file is missing or unsafe: {name}")
            continue
        if _sha256(path.read_bytes()) != expected_digest:
            errors.append(f"checksum mismatch: {name}")

    return {"status": "PASS" if not errors else "FAIL", "errors": errors}
