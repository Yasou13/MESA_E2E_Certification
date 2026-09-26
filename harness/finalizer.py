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

from pydantic import ValidationError

from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, MANDATORY_REPOSITORIES
from harness.models import EvidenceIndex, VerdictStatus
from harness.gates import PROFILE_B_GATE_IDS, PRODUCTION_METRIC_PRODUCERS
from harness.evidence import _confined_path, EvidenceIndexError, sha256_file


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

    if name == "evidence-index.json":
        try:
            ev_model = EvidenceIndex.model_validate(payload)
        except ValidationError as exc:
            raise ReleaseFinalizationError(f"evidence-index.json fails schema: {exc}") from exc
        if ev_model.index_hash:
            entries_for_hash = [
                {"path": art.path, "sha256": art.sha256}
                for art in sorted(ev_model.artifacts, key=lambda item: item.path)
            ]
            canonical_bytes = json.dumps(
                entries_for_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            observed_index_hash = hashlib.sha256(canonical_bytes).hexdigest()
            if observed_index_hash != ev_model.index_hash:
                raise ReleaseFinalizationError("evidence-index index_hash integrity mismatch")
        for art in ev_model.artifacts:
            if art.source_run_id != run_id:
                raise ReleaseFinalizationError(
                    f"unauthorized foreign source_run_id in evidence index: {art.source_run_id} for {art.path}"
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

    # 1. Run lifecycle terminal state validation
    run_manifest = payloads.get("run_manifest.json")
    if isinstance(run_manifest, dict):
        manifest_status = run_manifest.get("status")
        if manifest_status in {"FAIL", "INVALIDATED", "BLOCKED", "INVALID", "UNVERIFIED"}:
            raise ReleaseFinalizationError(f"run lifecycle is invalid: {manifest_status}")
        if run_manifest.get("lifecycle_valid") is False:
            raise ReleaseFinalizationError("run lifecycle terminal state is invalid")
        if run_manifest.get("lifecycle_status") in {"FAIL", "INVALIDATED", "BLOCKED", "INVALID"}:
            raise ReleaseFinalizationError(
                f"run lifecycle terminal state is invalid: {run_manifest.get('lifecycle_status')}"
            )

    # 2. Contract freeze validation
    contract_freeze = payloads.get("contract-freeze.json")
    if isinstance(contract_freeze, dict):
        freeze_status = contract_freeze.get("status")
        if freeze_status in {
            "FAIL",
            "INVALID_FREEZE",
            "FREEZE_INVALID",
            "MISSING_FREEZE",
            "INVALIDATED_CODE_CHANGE",
            "FREEZE_MISSING_REQUIRED_MATERIAL",
            "FREEZE_REPOSITORY_IDENTITY_MISSING",
            "FREEZE_HASH_MISMATCH",
        }:
            raise ReleaseFinalizationError(f"contract freeze is invalid: {freeze_status}")
        if contract_freeze.get("freeze_valid") is False:
            raise ReleaseFinalizationError("contract freeze is invalid")
        repos = contract_freeze.get("repository_shas")
        if isinstance(repos, dict):
            missing_repos = sorted(MANDATORY_REPOSITORIES - set(repos.keys()))
            if missing_repos:
                raise ReleaseFinalizationError(
                    f"contract freeze missing mandatory repositories: {missing_repos}"
                )
        materials = contract_freeze.get("materials")
        if isinstance(materials, list) and materials:
            present_cats = {
                m.get("category") for m in materials if isinstance(m, dict)
            }
            missing_cats = sorted(MANDATORY_MATERIAL_CATEGORIES - present_cats)
            if missing_cats:
                raise ReleaseFinalizationError(
                    f"contract freeze missing mandatory material categories: {missing_cats}"
                )

    # 3. Oracle audit and raw sealing validation
    for name, pl in payloads.items():
        if isinstance(pl, dict):
            if pl.get("oracle_audit_stale") is True:
                raise ReleaseFinalizationError(f"oracle audit is stale in {name}")
            if pl.get("oracle_audit_status") in {"STALE", "FAIL"}:
                raise ReleaseFinalizationError(
                    f"oracle audit is {pl.get('oracle_audit_status')} in {name}"
                )

    # 4. Mandatory PASS artifacts
    for name in sorted(_REQUIRED_PASS_ARTIFACTS):
        if payloads[name].get("status") != "PASS":
            raise ReleaseFinalizationError(
                f"PASS release requires {name} status PASS"
            )

    # 5. Authoritative gate results recomputation
    gates = gate_results["gates"]
    gate_ids = [g.get("gate_id") for g in gates if isinstance(g, dict)]
    if len(gate_ids) != len(set(gate_ids)):
        raise ReleaseFinalizationError("duplicate gate results found in gate-results.json")

    mandatory_gate_ids: set[str] = set()
    if "mandatory_gate_ids" in gate_results:
        if isinstance(gate_results["mandatory_gate_ids"], list):
            mandatory_gate_ids = set(gate_results["mandatory_gate_ids"])
            missing = sorted(mandatory_gate_ids - set(gate_ids))
            if missing:
                raise ReleaseFinalizationError(
                    f"mandatory gate results missing: {missing}"
                )

    for g in gates:
        if not isinstance(g, dict):
            raise ReleaseFinalizationError("gate entry must be an object")
        gid = g.get("gate_id", "unknown")
        status = g.get("status")
        is_hard = g.get("hard", False) or (gid in mandatory_gate_ids)

        if is_hard and status != "PASS":
            raise ReleaseFinalizationError(
                f"hard gate {gid} has status {status}, cannot promote PASS release"
            )
        if status in {"FAIL", "UNVERIFIED", "BLOCKED"}:
            if is_hard:
                raise ReleaseFinalizationError(
                    f"hard gate {gid} failed or unverified: {status}"
                )

        reqs = g.get("requirements")
        obs = g.get("observed")
        if status == "PASS" and isinstance(reqs, dict) and isinstance(obs, dict):
            for metric, req in reqs.items():
                if metric not in obs:
                    raise ReleaseFinalizationError(
                        f"gate {gid} marked PASS but missing observed metric {metric}"
                    )
                val = obs[metric]
                op = req.get("operator") if isinstance(req, dict) else None
                expected_val = req.get("value") if isinstance(req, dict) else None
                if op == "gte" and val < expected_val:
                    raise ReleaseFinalizationError(
                        f"gate {gid} marked PASS but observed metric {metric}={val} fails requirements (gte {expected_val})"
                    )
                elif op == "lte" and val > expected_val:
                    raise ReleaseFinalizationError(
                        f"gate {gid} marked PASS but observed metric {metric}={val} fails requirements (lte {expected_val})"
                    )
                elif op == "eq" and val != expected_val:
                    raise ReleaseFinalizationError(
                        f"gate {gid} marked PASS but observed metric {metric}={val} fails requirements (eq {expected_val})"
                    )

    any_failed = any(
        (g.get("hard", False) or g.get("gate_id") in mandatory_gate_ids)
        and g.get("status") != "PASS"
        for g in gates
    )
    if any_failed:
        raise ReleaseFinalizationError(
            "tampered final_verdict: hard gate failed but verdict claimed PASS"
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

    # Verify the real index producer's references against source bytes, not just
    # the self-consistency of its serialized digest list.
    index = EvidenceIndex.model_validate(json_payloads["evidence-index.json"])
    if not index.artifacts or not index.index_hash or index.artifact_count != len(index.artifacts):
        raise ReleaseFinalizationError("empty or incomplete evidence index")
    evidence_root = Path(sources["evidence-index.json"]).parent
    for artifact in index.artifacts:
        try:
            path = _confined_path(evidence_root, artifact.path)
        except EvidenceIndexError as exc:
            raise ReleaseFinalizationError(str(exc)) from exc
        if not path.is_file() or path.is_symlink() or sha256_file(path) != artifact.sha256:
            raise ReleaseFinalizationError(f"evidence artifact missing or hash mismatch: {artifact.path}")

    if json_payloads["gate-results.json"]["final_verdict"] == VerdictStatus.PROFILE_B_PASS_NATIVE.value:
        gates = json_payloads["gate-results.json"]["gates"]
        if {g["gate_id"] for g in gates} != PROFILE_B_GATE_IDS:
            raise ReleaseFinalizationError("mandatory gate registry must contain exactly B0-B14")
        unavailable = sorted(PROFILE_B_GATE_IDS - PRODUCTION_METRIC_PRODUCERS)
        if unavailable:
            raise ReleaseFinalizationError(
                f"unverified authoritative metric producers for mandatory gates: {unavailable}"
            )

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
