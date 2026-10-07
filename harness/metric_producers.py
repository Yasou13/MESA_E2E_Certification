"""Authoritative, artifact-derived B0-B14 metric producers.

Each producer consumes a fixed current-run artifact name, verifies its seal and
identity, and derives observations from primitive measurements.  Serialized
PASS/verdict fields are intentionally ignored.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from harness.artifacts import canonical_json_bytes
from harness.freeze import FreezeStatus, verify_contract_freeze
from harness.operations import (
    HealthPhase,
    HealthSnapshot,
    OperationalStatus,
    ResourcePressureEvent,
    ResourceSample,
    capture_health_snapshot,
    evaluate_resource_status,
)

if TYPE_CHECKING:
    from harness.execution_provenance import OfficialExecutionSession


PRODUCER_VERSION = "1.0"
PRODUCTION_GATE_IDS = frozenset(f"B{i}" for i in range(15))


class ProducerIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class ProducerContext:
    run_dir: Path
    run_id: str
    freeze_path: Path
    checksum_path: Path
    repository_root: Path
    current_repository_shas: dict[str, str]
    raw_manifest_hash: str
    gate_config_path: Path
    execution_mode: str = "test"
    execution_session: "OfficialExecutionSession | None" = None


@dataclass(frozen=True)
class ProducerObservation:
    gate_id: str
    execution: str
    observed: dict[str, Any]
    evidence: tuple[str, ...]
    reason: str
    producer_version: str = PRODUCER_VERSION


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _official_contract(ctx: ProducerContext) -> dict[str, Any]:
    try:
        payload = json.loads(ctx.gate_config_path.read_text(encoding="utf-8"))
        contract = payload["official_contract"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProducerIntegrityError(
            f"canonical Profile B contract is unavailable: {exc}"
        ) from exc
    if not isinstance(contract, dict):
        raise ProducerIntegrityError("canonical Profile B contract must be an object")
    return contract


def _evidence(path: Path, run_dir: Path) -> str:
    return f"{path.relative_to(run_dir).as_posix()}#sha256={_sha256(path)}"


def _bounded_path(root: Path, relative: Any, field: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ProducerIntegrityError(f"{field} must be a non-empty relative path")
    base = root.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ProducerIntegrityError(f"{field} escapes its authority root") from exc
    return path


def _verify_sidecar(path: Path) -> None:
    sidecar = path.with_suffix(path.suffix + ".SHA256")
    if not path.is_file() or not sidecar.is_file():
        raise ProducerIntegrityError(f"missing sealed artifact: {path.name}")
    parts = sidecar.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[1] != path.name or parts[0] != _sha256(path):
        raise ProducerIntegrityError(f"artifact seal mismatch: {path.name}")


def _json(ctx: ProducerContext, name: str) -> tuple[dict[str, Any], Path]:
    path = ctx.run_dir / name
    _verify_sidecar(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProducerIntegrityError(f"invalid JSON artifact {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProducerIntegrityError(f"artifact {name} must be an object")
    if value.get("schema_version") not in {"1.0", "2.0"}:
        raise ProducerIntegrityError(f"unsupported schema_version in {name}")
    if value.get("run_id") != ctx.run_id:
        raise ProducerIntegrityError(f"RUN_ID mismatch in {name}")
    return value, path


def _jsonl(ctx: ProducerContext, name: str, model) -> tuple[list[Any], Path]:
    path = ctx.run_dir / name
    _verify_sidecar(path)
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = model.model_validate_json(line)
        except Exception as exc:
            raise ProducerIntegrityError(f"invalid {name} line {number}") from exc
        if row.run_id != ctx.run_id:
            raise ProducerIntegrityError(f"RUN_ID mismatch in {name}:{number}")
        rows.append(row)
    return rows, path


def write_sealed_measurement(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a deterministic producer input plus adjacent SHA-256 seal."""

    target = Path(path)
    serialized = (
        json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        + "\n"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") != serialized:
        raise ProducerIntegrityError(f"refusing to overwrite measurement: {target}")
    target.write_text(serialized, encoding="utf-8", newline="\n")
    digest = _sha256(target)
    target.with_suffix(target.suffix + ".SHA256").write_text(
        f"{digest}  {target.name}\n", encoding="utf-8", newline="\n"
    )
    return target


def frozen_producer_code_sha256(ctx: ProducerContext) -> str:
    """Verify and hash the exact producer, evaluator, transaction and thresholds."""

    try:
        freeze = json.loads(ctx.freeze_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProducerIntegrityError(f"cannot read producer authority: {exc}") from exc
    if freeze.get("run_id") != ctx.run_id:
        raise ProducerIntegrityError("producer authority RUN_ID mismatch")
    materials = freeze.get("materials")
    if not isinstance(materials, list):
        raise ProducerIntegrityError("producer authority materials are malformed")
    frozen: dict[str, tuple[str, str]] = {}
    for item in materials:
        if not isinstance(item, dict):
            raise ProducerIntegrityError("producer authority material row is malformed")
        rel, category, digest = (
            item.get("path"),
            item.get("category"),
            item.get("sha256"),
        )
        if not all(isinstance(value, str) for value in (rel, category, digest)):
            raise ProducerIntegrityError(
                "producer authority material row has invalid types"
            )
        frozen[rel] = (category, digest)

    source_root = Path(__file__).resolve().parents[1]
    required = {
        "harness/answer_execution.py": (
            "harness_source",
            source_root / "harness" / "answer_execution.py",
        ),
        "harness/artifacts.py": (
            "harness_source",
            source_root / "harness" / "artifacts.py",
        ),
        "harness/execution_provenance.py": (
            "harness_source",
            source_root / "harness" / "execution_provenance.py",
        ),
        "harness/metric_producers.py": ("harness_source", Path(__file__).resolve()),
        "harness/gates.py": ("harness_source", source_root / "harness" / "gates.py"),
        "harness/transaction.py": (
            "harness_source",
            source_root / "harness" / "transaction.py",
        ),
        "harness/scope_collector.py": (
            "harness_source",
            source_root / "harness" / "scope_collector.py",
        ),
        "harness/graph_collector.py": (
            "harness_source",
            source_root / "harness" / "graph_collector.py",
        ),
        "harness/state_proof.py": (
            "harness_source",
            source_root / "harness" / "state_proof.py",
        ),
        "harness/mesa_adapters.py": (
            "harness_source",
            source_root / "harness" / "mesa_adapters.py",
        ),
        "harness/mesa_transport.py": (
            "harness_source",
            source_root / "harness" / "mesa_transport.py",
        ),
        "harness/qualification_runner.py": (
            "harness_source",
            source_root / "harness" / "qualification_runner.py",
        ),
        "harness/finalizer.py": (
            "harness_source",
            source_root / "harness" / "finalizer.py",
        ),
        "harness/verdict.py": (
            "harness_source",
            source_root / "harness" / "verdict.py",
        ),
        "harness/official_scoring.py": (
            "scorer_source",
            source_root / "harness" / "official_scoring.py",
        ),
        "config/profile-b-gates.json": ("thresholds", ctx.gate_config_path.resolve()),
    }
    authority_rows = []
    root = ctx.repository_root.resolve()
    for rel, (expected_category, execution_path) in required.items():
        frozen_row = frozen.get(rel)
        if frozen_row is None:
            raise ProducerIntegrityError(f"producer authority is missing {rel}")
        category, digest = frozen_row
        if category != expected_category:
            raise ProducerIntegrityError(
                f"producer authority category mismatch for {rel}: {category}"
            )
        frozen_path = (root / rel).resolve()
        try:
            frozen_path.relative_to(root)
        except ValueError as exc:
            raise ProducerIntegrityError(
                f"producer authority path escapes root: {rel}"
            ) from exc
        if (
            not frozen_path.is_file()
            or not execution_path.is_file()
            or _sha256(frozen_path) != digest
            or _sha256(execution_path) != digest
        ):
            raise ProducerIntegrityError(
                f"producer execution source differs from frozen authority: {rel}"
            )
        authority_rows.append({"path": rel, "sha256": digest})
    return hashlib.sha256(canonical_json_bytes(authority_rows)).hexdigest()


def _load_and_verify_raw_manifest(ctx: ProducerContext) -> dict[str, str]:
    """Verify raw-manifest.json in run_dir against context and return {path: sha256}."""
    manifest_path = ctx.run_dir / "raw-manifest.json"
    _verify_sidecar(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProducerIntegrityError(f"invalid raw-manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ProducerIntegrityError("raw-manifest.json must be an object")
    if manifest.get("run_id") != ctx.run_id:
        raise ProducerIntegrityError(
            f"raw-manifest.json run_id mismatch: {manifest.get('run_id')} != {ctx.run_id}"
        )
    if manifest.get("manifest_hash") != ctx.raw_manifest_hash:
        raise ProducerIntegrityError(
            f"raw-manifest.json manifest_hash mismatch: {manifest.get('manifest_hash')} != {ctx.raw_manifest_hash}"
        )
    if ctx.execution_mode == "official":
        if ctx.execution_session is None:
            raise ProducerIntegrityError(
                "official metric production lacks active execution authority"
            )
        try:
            ctx.execution_session.verify_raw_manifest(manifest, ctx.raw_manifest_hash)
        except Exception as exc:
            raise ProducerIntegrityError(
                f"raw manifest is not rooted in official execution: {exc}"
            ) from exc
    elif ctx.execution_mode != "test":
        raise ProducerIntegrityError(
            f"unsupported metric execution mode: {ctx.execution_mode!r}"
        )
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ProducerIntegrityError("raw-manifest.json entries must be a list")
    manifest_map: dict[str, str] = {}
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not entry.get("path")
            or not entry.get("sha256")
        ):
            raise ProducerIntegrityError("raw-manifest.json entry malformed")
        manifest_map[entry["path"]] = entry["sha256"]
    return manifest_map


def _blocked(gate_id: str, reason: str) -> ProducerObservation:
    return ProducerObservation(gate_id, "BLOCKED", {}, (), reason)


def _completed(
    gate_id: str, observed: dict[str, Any], paths: list[Path], ctx: ProducerContext
) -> ProducerObservation:
    reason = (
        "authoritative_artifacts_recomputed"
        if ctx.execution_mode == "official"
        else "non_authoritative_test_artifacts_recomputed"
    )
    return ProducerObservation(
        gate_id,
        "COMPLETED",
        observed,
        tuple(_evidence(path, ctx.run_dir) for path in paths),
        reason,
    )


def _require_official_runner_owned(
    ctx: ProducerContext, path: Path, artifact_type: str
) -> None:
    if ctx.execution_mode != "official":
        return
    if ctx.execution_session is None:
        raise ProducerIntegrityError(
            f"{artifact_type} lacks active official execution authority"
        )
    try:
        ctx.execution_session.verify_derived_artifact(path, artifact_type)
    except Exception as exc:
        raise ProducerIntegrityError(
            f"{artifact_type} is not runner-owned authoritative evidence: {exc}"
        ) from exc


def _b0(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "baseline-evidence.json")
    repositories = data.get("repositories")
    ci_runs = data.get("ci_runs")
    dependency = data.get("dependency_lock")
    if (
        not isinstance(repositories, list)
        or not isinstance(ci_runs, list)
        or not isinstance(dependency, dict)
    ):
        raise ProducerIntegrityError("B0 baseline evidence shape is invalid")
    expected = {"MESA", "MESA_Data", "MESA_E2E_Certification"}
    by_name = {row.get("name"): row for row in repositories if isinstance(row, dict)}
    clean = set(by_name) == expected and all(
        row.get("dirty_paths") == [] for row in by_name.values()
    )
    dedicated = clean and all(
        row.get("branch") not in {"main", "master", ""} for row in by_name.values()
    )
    exact_ci = clean and all(
        any(
            ci.get("repository") == name
            and ci.get("sha") == row.get("sha")
            and ci.get("conclusion") == "success"
            for ci in ci_runs
            if isinstance(ci, dict)
        )
        for name, row in by_name.items()
    )
    lock_path = _bounded_path(
        ctx.repository_root, dependency.get("path"), "dependency_lock.path"
    )
    reproducible = (
        lock_path.is_file()
        and dependency.get("sha256") == _sha256(lock_path)
        and dependency.get("lock_check_exit_code") == 0
        and dependency.get("sync_exit_code") == 0
    )
    return _completed(
        "B0",
        {
            "ci_actions_passed": exact_ci,
            "clean_baseline_verified": clean,
            "dedicated_branch_verified": dedicated,
            "dependencies_reproducible": reproducible,
        },
        [path],
        ctx,
    )


def _b1(ctx: ProducerContext) -> ProducerObservation:
    workspace, wp = _json(ctx, "workspace-baseline.json")
    environment, ep = _json(ctx, "environment-baseline.json")
    ram = environment.get("ram_total_bytes")
    disk = environment.get("disk_free_bytes")
    if (
        isinstance(ram, bool)
        or isinstance(disk, bool)
        or not isinstance(ram, int)
        or not isinstance(disk, int)
        or ram < 0
        or disk < 0
    ):
        raise ProducerIntegrityError("B1 resource measurements are invalid")
    isolated = all(
        workspace.get(key) is expected
        for key, expected in {
            "old_runtime_reused": False,
            "mesa_storage_clean": True,
            "mesa_data_root_clean": True,
            "unknown_files_deleted": False,
            "secrets_printed": False,
            "docker_state_inventoried": True,
            "docker_state_isolated": True,
        }.items()
    )
    gib = 1024**3
    return _completed(
        "B1",
        {
            "ram_min_gb": ram / gib,
            "disk_min_gb": disk / gib,
            "isolated_storage_verified": isolated,
        },
        [wp, ep],
        ctx,
    )


def _b2(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "provider-canary.json")
    providers = _official_contract(ctx).get("providers")
    if not isinstance(providers, dict):
        raise ProducerIntegrityError("canonical provider contract is missing")
    embedding = providers.get("embedding")
    extraction_contract = providers.get("extraction")
    if not isinstance(embedding, dict) or not isinstance(extraction_contract, dict):
        raise ProducerIntegrityError("canonical embedding/extraction contract is missing")
    document = data.get("document_embedding")
    query = data.get("query_embedding")
    if not isinstance(document, list) or not isinstance(query, list):
        raise ProducerIntegrityError("B2 embeddings must be arrays")
    finite = all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        for v in [*document, *query]
    )
    dim = len(document) == len(query) == embedding.get("dimension")
    asymmetric = (
        document != query
        and data.get("document_input_type") == embedding.get("document_input_type")
        and data.get("query_input_type") == embedding.get("query_input_type")
    )
    request_ids = data.get("provider_request_ids")
    real = (
        data.get("provider") == embedding.get("provider")
        and data.get("endpoint") == embedding.get("endpoint")
        and data.get("embedding_model") == embedding.get("model")
        and data.get("extraction_model") == extraction_contract.get("model")
        and isinstance(request_ids, list)
        and bool(request_ids)
        and all(isinstance(item, str) and item for item in request_ids)
        and len(request_ids) == len(set(request_ids))
    )
    expected_marker = data.get("completion_marker_expected")
    observed_marker = data.get("completion_marker_observed")
    completion = (
        isinstance(expected_marker, str)
        and bool(expected_marker)
        and observed_marker == expected_marker
    )
    extraction = isinstance(data.get("structured_extraction"), dict) and bool(
        data["structured_extraction"].get("facts")
    )
    return _completed(
        "B2",
        {
            "nemotron_dim_verified": dim and finite and asymmetric,
            "gpt_oss_completion_verified": completion and extraction,
            "real_provider_contract_verified": real,
        },
        [path],
        ctx,
    )


def _b3(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "runtime-config-parity.json")
    intended, container, effective = (
        data.get(name) for name in ("intended", "container", "effective")
    )
    if not all(
        isinstance(value, dict) and value for value in (intended, container, effective)
    ):
        raise ProducerIntegrityError("B3 parity maps are missing")
    parity = intended == container == effective
    providers = _official_contract(ctx)["providers"]
    embedding = providers["embedding"]
    extraction = providers["extraction"]
    canonical = {
        "MESA_MODEL_ENABLED": True,
        "MESA_TIER3_MODE": 0,
        "MESA_EXTERNAL_PROVIDER_ENABLED": True,
        "MESA_EXTERNAL_EMBEDDING_MODEL": embedding["model"],
        "MESA_EMBEDDING_DIMENSION": embedding["dimension"],
        "MESA_EXTRACTION_MODEL": extraction["model"],
        "MESA_EXTRACTION_LANG": extraction["language"],
    }
    frozen = (
        all(effective.get(key) == value for key, value in canonical.items())
        and effective.get("MESA_EXTRACTION_MAX_TOKENS", 0)
        >= extraction["minimum_max_tokens"]
    )
    return _completed(
        "B3",
        {"docker_config_parity": parity, "frozen_provider_parity": frozen},
        [path],
        ctx,
    )


def _b4(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "corpus-integrity.json")
    _require_official_runner_owned(ctx, path, "corpus_integrity")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ProducerIntegrityError("B4 corpus items are missing")
    raw_ok = canonical_ok = True
    eligible = 0
    for item in items:
        if not isinstance(item, dict):
            raise ProducerIntegrityError("B4 corpus item is malformed")
        raw = _bounded_path(ctx.run_dir, item.get("raw_path"), "B4 raw_path")
        canonical = _bounded_path(
            ctx.run_dir, item.get("canonical_path"), "B4 canonical_path"
        )
        raw_ok &= raw.is_file() and item.get("raw_sha256") == _sha256(raw)
        canonical_ok &= (
            canonical.is_file()
            and canonical.stat().st_size > 0
            and item.get("canonical_sha256") == _sha256(canonical)
            and "�" not in canonical.read_text(encoding="utf-8")
        )
        checks = item.get("quality_checks")
        quality_passed = (
            isinstance(checks, dict)
            and bool(checks)
            and all(value is True for value in checks.values())
        )
        if quality_passed:
            eligible += 1
    return _completed(
        "B4",
        {
            "eligible_document_count": eligible,
            "encoding_canonical_verified": canonical_ok,
            "raw_integrity_verified": raw_ok,
        },
        [path],
        ctx,
    )


def _b5(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "human-approval.json")
    if ctx.execution_mode == "official":
        try:
            freeze = json.loads(ctx.freeze_path.read_text(encoding="utf-8"))
            expected_approval_hash = freeze["runtime_identities"][
                "upstream_authority"
            ]["human_approval_sha256"]
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ) as exc:
            raise ProducerIntegrityError(
                "B5 frozen human-approval authority is unavailable"
            ) from exc
        if expected_approval_hash != _sha256(path):
            raise ProducerIntegrityError(
                "B5 human approval differs from frozen external authority"
            )
    release_hash = data.get("release_manifest_sha256")
    selected_hash = data.get("selected_versions_manifest_sha256")
    h1a = data.get("h1a_literal_decision", "")
    h1b = data.get("h1b_literal_decision", "")
    selected_path = _bounded_path(
        ctx.run_dir,
        data.get("selected_versions_manifest_path"),
        "selected_versions_manifest_path",
    )
    release_path = _bounded_path(
        ctx.run_dir, data.get("release_manifest_path"), "release_manifest_path"
    )
    expected_h1a = f"H1A APPROVE CORPUS {ctx.run_id} {str(selected_hash)[:12]}"
    expected_h1b = f"H1B APPROVE DELIVERY {ctx.run_id} {str(release_hash)[:12]}"
    bound = (
        isinstance(release_hash, str)
        and isinstance(selected_hash, str)
        and len(release_hash) == len(selected_hash) == 64
        and selected_path.is_file()
        and release_path.is_file()
        and _sha256(selected_path) == selected_hash
        and _sha256(release_path) == release_hash
        and isinstance(h1a, str)
        and isinstance(h1b, str)
        and h1a == expected_h1a
        and h1b == expected_h1b
    )
    return _completed(
        "B5",
        {"h1_approval_hash_bound": bound, "delivery_permission_granted": bound},
        [path, selected_path, release_path],
        ctx,
    )


def _b6(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "native-canary.json")
    _require_official_runner_owned(ctx, path, "native_canary")
    native = (
        data.get("publisher_component") == "MESA_Data"
        and data.get("publish_route") == "/v4/memory/insert"
        and data.get("diagnostic_bridge_used") is False
    )
    before_count = data.get("logical_count_before_retry")
    after_count = data.get("logical_count_after_retry")
    passed = (
        data.get("mutation_state") == "COMMITTED"
        and isinstance(data.get("source_chunk_id"), str)
        and bool(data.get("source_chunk_id"))
        and data.get("search_source_chunk_id") == data.get("source_chunk_id")
        and isinstance(before_count, int)
        and not isinstance(before_count, bool)
        and isinstance(after_count, int)
        and not isinstance(after_count, bool)
        and before_count > 0
        and after_count == before_count
    )
    return _completed(
        "B6", {"canary_passed": passed, "no_bridge_substitution": native}, [path], ctx
    )


def _b7(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "delivery-evidence.json")
    _require_official_runner_owned(ctx, path, "delivery_evidence")
    planned, delivered = data.get("planned_source_chunk_ids"), data.get("deliveries")
    if not isinstance(planned, list) or not isinstance(delivered, list) or not planned:
        raise ProducerIntegrityError("B7 delivery populations are missing")
    if (
        any(not isinstance(item, str) or not item for item in planned)
        or len(planned) != len(set(planned))
        or any(not isinstance(row, dict) for row in delivered)
    ):
        raise ProducerIntegrityError(
            "B7 delivery population contains duplicates or invalid rows"
        )
    terminal = {
        row.get("source_chunk_id")
        for row in delivered
        if row.get("terminal_state") in {"COMMITTED", "ALREADY_COMMITTED"}
        and row.get("mesa_chunk_id")
        and row.get("mutation_id")
    }
    undelivered = len(set(planned) - terminal)
    delivered_ids = [row.get("source_chunk_id") for row in delivered]
    mapping = (
        len(delivered_ids) == len(set(delivered_ids))
        and set(delivered_ids) == set(planned)
        and len(terminal) == len(planned)
    )
    return _completed(
        "B7",
        {
            "chunk_mapping_proven": mapping,
            "delivery_terminal_committed": undelivered == 0,
            "undelivered_chunk_count": undelivered,
        },
        [path],
        ctx,
    )


def _b8(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "restart-idempotency.json")
    _require_official_runner_owned(ctx, path, "restart_idempotency")
    before, after = data.get("before_restart_probe"), data.get("after_restart_probe")
    persistence = (
        isinstance(before, dict)
        and bool(before)
        and isinstance(after, dict)
        and before == after
        and data.get("restart_observed") is True
    )
    before_count = data.get("logical_count_before_republish")
    after_count = data.get("logical_count_after_republish")
    idempotent = (
        isinstance(before_count, int)
        and not isinstance(before_count, bool)
        and isinstance(after_count, int)
        and not isinstance(after_count, bool)
        and before_count > 0
        and before_count == after_count
        and data.get("stable_idempotency_key") is True
        and data.get("republish_terminal_state")
        in {"COMMITTED", "ALREADY_COMMITTED", "SKIPPED_COMMITTED"}
    )
    return _completed(
        "B8",
        {
            "restart_persistence_proven": persistence,
            "idempotent_republish_proven": idempotent,
        },
        [path],
        ctx,
    )


def _validate_scope_cases(
    scope: dict[str, Any], scope_path: Path, ctx: ProducerContext, gate_name: str
) -> tuple[int, list[Path]]:
    frozen_case_fixtures: dict[str, Any] | None = None
    frozen_fixture_hash: str | None = None
    if ctx.execution_mode == "official":
        if ctx.execution_session is None:
            raise ProducerIntegrityError(
                f"{gate_name} lacks active official execution authority"
            )
        try:
            ctx.execution_session.verify_derived_artifact(scope_path, "scope_isolation")
        except Exception as exc:
            raise ProducerIntegrityError(
                f"{gate_name} scope evidence is not runner-owned: {exc}"
            ) from exc
        try:
            freeze = json.loads(ctx.freeze_path.read_text(encoding="utf-8"))
            runtime = freeze["runtime_identities"]
            fixture_authority = runtime["scope_test_authority"]
            frozen_case_fixtures = fixture_authority["case_evidence_fixtures"]
            frozen_fixture_hash = hashlib.sha256(
                canonical_json_bytes(fixture_authority)
            ).hexdigest()
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ) as exc:
            raise ProducerIntegrityError(
                f"{gate_name} frozen Phase 7 fixture authority is unavailable"
            ) from exc
        if scope.get("fixture_authority_hash") != frozen_fixture_hash:
            raise ProducerIntegrityError(
                f"{gate_name} scope fixture authority differs from contract freeze"
            )
    if scope.get("run_id") != ctx.run_id:
        raise ProducerIntegrityError(
            f"{gate_name} scope artifact run_id mismatch: {scope.get('run_id')} != {ctx.run_id}"
        )
    mesa_repo_sha = ctx.current_repository_shas.get("MESA")
    if mesa_repo_sha and scope.get("mesa_sha") != mesa_repo_sha:
        raise ProducerIntegrityError(
            f"{gate_name} scope artifact mesa_sha mismatch: {scope.get('mesa_sha')} != {mesa_repo_sha}"
        )
    if (
        scope.get("producer")
        != "harness.scope_collector.collect_phase7_scope_isolation"
    ):
        raise ProducerIntegrityError(
            f"{gate_name} scope-isolation artifact lacks authoritative producer lineage"
        )
    if scope.get("contract_version") != "mesa.scope-audit.v1":
        raise ProducerIntegrityError(
            f"{gate_name} unsupported scope contract_version: {scope.get('contract_version')!r}"
        )

    # Validate raw execution lineage against sealed raw-manifest
    manifest_entries = _load_and_verify_raw_manifest(ctx)

    cases = scope.get("negative_cases")
    if (
        not isinstance(cases, list)
        or not cases
        or not all(isinstance(case, dict) for case in cases)
    ):
        raise ProducerIntegrityError(f"{gate_name} negative cases are missing")
    required_case_ids = {
        "cross_tenant_search",
        "cross_dataset_search",
        "cross_agent_search",
        "inactive_status_search",
        "wrong_jurisdiction_search",
        "stale_version_search",
        "effective_date_boundary_search",
        "context_visibility",
        "catalog_visibility",
        "document_visibility",
        "revision_visibility",
        "chunk_visibility",
    }
    case_ids = {case.get("case_id") for case in cases}
    if case_ids != required_case_ids:
        raise ProducerIntegrityError(f"{gate_name} negative-case matrix is incomplete")
    forbidden_lists = [case.get("returned_forbidden_evidence_ids") for case in cases]
    if any(
        not isinstance(values, list)
        or any(not isinstance(value, str) or not value for value in values)
        for values in forbidden_lists
    ):
        raise ProducerIntegrityError(
            f"{gate_name} forbidden-evidence observations are malformed"
        )

    search_case_ids = {
        "cross_tenant_search",
        "cross_dataset_search",
        "cross_agent_search",
        "inactive_status_search",
        "wrong_jurisdiction_search",
        "stale_version_search",
        "effective_date_boundary_search",
    }

    raw_paths: list[Path] = [scope_path]
    for case in cases:
        cid = case.get("case_id")
        if ctx.execution_mode == "official":
            fixture_ids = case.get("fixture_ids")
            if (
                case.get("fixture_authority_hash") != frozen_fixture_hash
                or not isinstance(fixture_ids, list)
                or fixture_ids != frozen_case_fixtures.get(cid)
            ):
                raise ProducerIntegrityError(
                    f"{gate_name} case {cid} is not bound to its frozen fixtures"
                )
        raw_rel = case.get("source_raw_artifact")
        if not isinstance(raw_rel, str) or not raw_rel.startswith("raw/scope/"):
            raise ProducerIntegrityError(
                f"{gate_name} case {cid} lacks authoritative source_raw_artifact in raw/scope/"
            )
        if raw_rel not in manifest_entries:
            raise ProducerIntegrityError(
                f"{gate_name} case {cid} source_raw_artifact is absent from sealed raw manifest"
            )
        if case.get("source_raw_sha256") != manifest_entries[raw_rel]:
            raise ProducerIntegrityError(
                f"{gate_name} case {cid} source_raw_sha256 does not match sealed raw manifest"
            )
        raw_file = ctx.run_dir / raw_rel
        _verify_sidecar(raw_file)
        try:
            raw_payload = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProducerIntegrityError(
                f"cannot read raw artifact {raw_rel}: {exc}"
            ) from exc
        if raw_payload.get("run_id") != ctx.run_id:
            raise ProducerIntegrityError(
                f"{gate_name} raw artifact {raw_rel} run_id mismatch: {raw_payload.get('run_id')} != {ctx.run_id}"
            )
        if raw_payload.get("case_id") != cid:
            raise ProducerIntegrityError(
                f"{gate_name} raw artifact {raw_rel} case_id mismatch: {raw_payload.get('case_id')} != {cid}"
            )
        if ctx.execution_mode == "official" and (
            raw_payload.get("fixture_authority_hash") != frozen_fixture_hash
            or raw_payload.get("fixture_ids") != frozen_case_fixtures.get(cid)
        ):
            raise ProducerIntegrityError(
                f"{gate_name} raw artifact {raw_rel} is not bound to frozen fixtures"
            )

        raw_hash = case.get("raw_response_sha256")
        if raw_hash is not None and (
            not isinstance(raw_hash, str) or len(raw_hash) != 64
        ):
            raise ProducerIntegrityError(
                f"{gate_name} case {cid} raw_response_sha256 is invalid"
            )

        if cid in search_case_ids:
            if case.get("proof_type") != "search_pre_rank_scope":
                raise ProducerIntegrityError(
                    f"{gate_name} search case {cid} must have proof_type='search_pre_rank_scope'"
                )
            if case.get("pre_rank_audit_verified") is not True:
                raise ProducerIntegrityError(
                    f"{gate_name} case {cid} pre_rank_audit_verified is not True"
                )
            hash_val = case.get("exclusion_audit_hash")
            if not isinstance(hash_val, str) or not hash_val.startswith("sha256:"):
                raise ProducerIntegrityError(
                    f"{gate_name} case {cid} exclusion_audit_hash is invalid"
                )
            eval_c = case.get("evaluated_candidate_count")
            excl_c = case.get("excluded_candidate_count")
            elig_c = case.get("eligible_candidate_count")
            if (
                not isinstance(eval_c, int)
                or not isinstance(excl_c, int)
                or not isinstance(elig_c, int)
                or eval_c != excl_c + elig_c
            ):
                raise ProducerIntegrityError(
                    f"{gate_name} case {cid} counts are incoherent"
                )
        else:
            # Non-search visibility cases - forbid pretending to have pre-rank audit
            if case.get("proof_type") != "endpoint_visibility":
                raise ProducerIntegrityError(
                    f"{gate_name} non-search case {cid} must have proof_type='endpoint_visibility'"
                )
            if case.get("pre_rank_audit_verified") is True:
                raise ProducerIntegrityError(
                    f"{gate_name} non-search case {cid} cannot claim pre_rank_audit_verified"
                )
            if case.get("exclusion_audit_hash") is not None:
                raise ProducerIntegrityError(
                    f"{gate_name} non-search case {cid} cannot synthesize exclusion_audit_hash"
                )
            if (
                case.get("evaluated_candidate_count") is not None
                or case.get("excluded_candidate_count") is not None
                or case.get("eligible_candidate_count") is not None
            ):
                raise ProducerIntegrityError(
                    f"{gate_name} non-search case {cid} cannot synthesize candidate counts"
                )
            if case.get("endpoint_visibility_verified") is not True:
                raise ProducerIntegrityError(
                    f"{gate_name} non-search case {cid} endpoint_visibility_verified is not True"
                )

        raw_paths.append(raw_file)

    leaks = sum(len(values) for values in forbidden_lists)
    return leaks, raw_paths


def _b9(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "scope-isolation.json")
    capabilities = data.get("mesa_contract_capabilities")
    if (
        not isinstance(capabilities, dict)
        or not capabilities.get("candidate_scope_identity")
        or not capabilities.get("pre_rank_exclusion_audit")
    ):
        return _blocked(
            "B9", "BLOCKED_BY_MESA_CONTRACT: candidate scope/pre-rank audit unavailable"
        )
    leaks, raw_paths = _validate_scope_cases(data, path, ctx, "B9")
    return _completed(
        "B9",
        {
            "cross_tenant_scope_leakage": leaks,
            "isolation_acl_passed": leaks == 0,
        },
        raw_paths,
        ctx,
    )


def _score_summary(ctx: ProducerContext) -> tuple[dict[str, Any], Path]:
    data, path = _json(ctx, "scoring-summary.json")
    if data.get("raw_manifest_hash") != ctx.raw_manifest_hash:
        raise ProducerIntegrityError("scoring summary raw-manifest mismatch")
    if data.get("scorer_version") != "profile-b-official-v2":
        raise ProducerIntegrityError("non-official scorer summary")
    return data, path


def _b10(ctx: ProducerContext) -> ProducerObservation:
    data, path = _score_summary(ctx)
    scope, scope_path = _json(ctx, "scope-isolation.json")
    capabilities = scope.get("mesa_contract_capabilities")
    if (
        not isinstance(capabilities, dict)
        or capabilities.get("candidate_scope_identity") is not True
        or capabilities.get("pre_rank_exclusion_audit") is not True
    ):
        return _blocked(
            "B10",
            "BLOCKED_BY_MESA_CONTRACT: tenant leakage cannot be measured without "
            "candidate scope identity and pre-rank exclusion audit",
        )
    leaks, raw_paths = _validate_scope_cases(scope, scope_path, ctx, "B10")

    metrics = data.get("metrics")
    if (
        not isinstance(metrics, dict)
        or data.get("lane_status", {}).get("retrieval") != "PASS"
    ):
        raise ProducerIntegrityError("B10 retrieval population is incomplete")
    required = (
        "answerable_mrr",
        "answerable_recall_at_5",
        "rel_complete_evidence_at_5",
        "single_hop_recall_at_5",
    )
    if any(metrics.get(key) is None for key in required):
        raise ProducerIntegrityError("B10 required measured population is empty")
    expected_population = {
        "retrieval_population": 80,
        "answerable_population": 70,
        "single_hop_population": 60,
        "rel_population": 10,
    }
    if any(metrics.get(key) != value for key, value in expected_population.items()):
        raise ProducerIntegrityError("B10 frozen TEST population is not 40/20/10/10")

    return _completed(
        "B10",
        {**{key: metrics[key] for key in required}, "tenant_leakage": leaks},
        [path] + raw_paths,
        ctx,
    )


def _b11(ctx: ProducerContext) -> ProducerObservation:
    data, path = _json(ctx, "graph-ablation.json")
    if ctx.execution_mode == "official":
        if ctx.execution_session is None:
            raise ProducerIntegrityError(
                "B11 lacks active official execution authority"
            )
        try:
            ctx.execution_session.verify_derived_artifact(path, "graph_ablation")
        except Exception as exc:
            raise ProducerIntegrityError(
                f"B11 graph evidence is not runner-owned: {exc}"
            ) from exc
    caps = data.get("mesa_contract_capabilities")
    if (
        not isinstance(caps, dict)
        or not caps.get("stable_path_identity")
        or not caps.get("native_graph_on_off_switch")
    ):
        return _blocked(
            "B11",
            "BLOCKED_BY_MESA_CONTRACT: native stable graph ON/OFF contract unavailable",
        )
    if data.get("run_id") != ctx.run_id:
        raise ProducerIntegrityError(
            f"B11 graph artifact run_id mismatch: {data.get('run_id')} != {ctx.run_id}"
        )
    mesa_repo_sha = ctx.current_repository_shas.get("MESA")
    if mesa_repo_sha and data.get("mesa_sha") != mesa_repo_sha:
        raise ProducerIntegrityError(
            f"B11 graph artifact mesa_sha mismatch: {data.get('mesa_sha')} != {mesa_repo_sha}"
        )
    if data.get("producer") != "harness.graph_collector.execute_paired_graph_ablation":
        raise ProducerIntegrityError(
            "B11 graph-ablation artifact lacks authoritative producer lineage"
        )
    if data.get("contract_version") != "mesa.graph-ablation.v1":
        raise ProducerIntegrityError(
            f"B11 unsupported graph contract_version: {data.get('contract_version')!r}"
        )

    # Validate raw execution lineage against sealed raw-manifest
    manifest_entries = _load_and_verify_raw_manifest(ctx)

    state_proof_rel = data.get("state_proof_artifact")
    if not isinstance(state_proof_rel, str) or not state_proof_rel.startswith(
        "raw/state/"
    ):
        raise ProducerIntegrityError(
            "B11 lacks authoritative state_proof_artifact in raw/state/"
        )
    if state_proof_rel not in manifest_entries:
        raise ProducerIntegrityError(
            "B11 state_proof_artifact is absent from sealed raw manifest"
        )
    if data.get("state_proof_sha256") != manifest_entries[state_proof_rel]:
        raise ProducerIntegrityError(
            "B11 state_proof_sha256 does not match sealed raw manifest"
        )
    state_proof_file = ctx.run_dir / state_proof_rel
    _verify_sidecar(state_proof_file)
    try:
        sealed_state_proof = json.loads(state_proof_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProducerIntegrityError(
            f"cannot read state proof {state_proof_rel}: {exc}"
        ) from exc
    if sealed_state_proof.get("run_id") != ctx.run_id:
        raise ProducerIntegrityError(
            f"B11 state proof run_id mismatch: {sealed_state_proof.get('run_id')} != {ctx.run_id}"
        )
    if sealed_state_proof.get("collector_version") != "harness.state_proof.v2":
        raise ProducerIntegrityError(
            "B11 state proof lacks authoritative collector lineage"
        )

    pre_fp = sealed_state_proof.get("pre_composite_fingerprint")
    post_fp = sealed_state_proof.get("post_composite_fingerprint")
    unchanged = sealed_state_proof.get("retrieval_state_unchanged") is True
    if not pre_fp or not post_fp or pre_fp != post_fp or not unchanged:
        return _blocked(
            "B11",
            "BLOCKED_BY_RUNTIME_STATE_PROOF: composite store fingerprint mutated during paired execution",
        )

    proof = data.get("frozen_state_proof")
    if not isinstance(proof, dict):
        raise ProducerIntegrityError("B11 frozen_state_proof is missing")
    if proof.get("retrieval_state_unchanged") is not True:
        return _blocked(
            "B11",
            "BLOCKED_BY_RUNTIME_STATE_PROOF: retrieval state not proven unchanged",
        )

    # B11 needs same effective retrieval state, not an unsupported claim that
    # all activity inside the live runtime was frozen.
    if (
        proof.get("quiescence_verified") is True
        or proof.get("runtime_quiescence_verified") is True
    ):
        raise ProducerIntegrityError(
            "B11 graph artifact falsely claims runtime quiescence"
        )
    pair_stable = (
        sealed_state_proof.get("proof_mode") == "stable_state_pair"
        and sealed_state_proof.get("pair_state_stability_verified") is True
        and sealed_state_proof.get("runtime_quiescence_verified") is False
    )
    graph_claims_pair_stability = (
        proof.get("proof_mode") == "stable_state_pair"
        and proof.get("pair_state_stability_verified") is True
    )
    if graph_claims_pair_stability and not pair_stable:
        raise ProducerIntegrityError(
            "B11 graph artifact falsely claims paired state stability"
        )
    if not pair_stable:
        return _blocked(
            "B11",
            "BLOCKED_BY_RUNTIME_STATE_PROOF: paired retrieval state stability not established",
        )
    if not graph_claims_pair_stability:
        raise ProducerIntegrityError(
            "B11 graph artifact does not mirror sealed paired state proof"
        )
    stability_evidence = sealed_state_proof.get("state_stability_evidence")
    if not isinstance(stability_evidence, dict):
        raise ProducerIntegrityError("B11 paired state-stability evidence is missing")
    if (
        stability_evidence.get("proof_mode") != "stable_state_pair"
        or stability_evidence.get("writer_lock_acquired_by_e2e") is not False
        or stability_evidence.get("pair_state_stability_verified") is not True
        or stability_evidence.get("runtime_quiescence_verified") is not False
        or stability_evidence.get("pre_writer_observation")
        != stability_evidence.get("post_writer_observation")
        or stability_evidence.get("pre_mutation_marker_sha256")
        != stability_evidence.get("post_mutation_marker_sha256")
    ):
        raise ProducerIntegrityError("B11 paired state-stability evidence is invalid")
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 10:
        raise ProducerIntegrityError("B11 requires exactly 10 REL graph pairs")

    contribution = 0
    positive = 0
    neutral = 0
    harm = 0
    provenance_valid = True
    query_ids: set[str] = set()
    graph_operational = True
    raw_files: list[Path] = [path, state_proof_file]

    for pair in pairs:
        if not isinstance(pair, dict):
            raise ProducerIntegrityError("B11 pair is malformed")
        on, off = pair.get("on"), pair.get("off")
        if not isinstance(on, dict) or not isinstance(off, dict):
            raise ProducerIntegrityError("B11 ON/OFF observation is malformed")

        # Validate raw lineage for both ON and OFF
        on_raw_rel = on.get("on_raw_artifact") or pair.get("on_raw_artifact")
        off_raw_rel = off.get("off_raw_artifact") or pair.get("off_raw_artifact")
        on_raw_sha = on.get("on_raw_sha256") or pair.get("on_raw_sha256")
        off_raw_sha = off.get("off_raw_sha256") or pair.get("off_raw_sha256")

        if not isinstance(on_raw_rel, str) or not on_raw_rel.startswith("raw/graph/"):
            raise ProducerIntegrityError(
                "B11 pair lacks authoritative on_raw_artifact in raw/graph/"
            )
        if not isinstance(off_raw_rel, str) or not off_raw_rel.startswith("raw/graph/"):
            raise ProducerIntegrityError(
                "B11 pair lacks authoritative off_raw_artifact in raw/graph/"
            )
        if on_raw_rel not in manifest_entries or off_raw_rel not in manifest_entries:
            raise ProducerIntegrityError(
                "B11 pair raw artifact is absent from sealed raw manifest"
            )
        if (
            on_raw_sha != manifest_entries[on_raw_rel]
            or off_raw_sha != manifest_entries[off_raw_rel]
        ):
            raise ProducerIntegrityError(
                "B11 pair raw sha does not match sealed raw manifest"
            )

        on_raw_file = ctx.run_dir / on_raw_rel
        off_raw_file = ctx.run_dir / off_raw_rel
        _verify_sidecar(on_raw_file)
        _verify_sidecar(off_raw_file)
        raw_files.extend([on_raw_file, off_raw_file])

        try:
            on_raw_payload = json.loads(on_raw_file.read_text(encoding="utf-8"))
            off_raw_payload = json.loads(off_raw_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProducerIntegrityError(f"cannot read raw graph pair: {exc}") from exc

        if (
            on_raw_payload.get("run_id") != ctx.run_id
            or off_raw_payload.get("run_id") != ctx.run_id
        ):
            raise ProducerIntegrityError("B11 pair raw artifact run_id mismatch")
        if (
            on_raw_payload.get("graph_enabled") is not True
            or off_raw_payload.get("graph_enabled") is not False
        ):
            raise ProducerIntegrityError("B11 pair raw artifact graph_enabled mismatch")

        identity_fields = (
            "query_id",
            "dataset_id",
            "mesa_sha",
            "settings_sha256",
        )
        matched = all(on.get(key) == off.get(key) for key in identity_fields)
        matched &= on.get("graph_enabled") is True and off.get("graph_enabled") is False
        if on.get("pair_identity") or off.get("pair_identity"):
            matched &= on.get("pair_identity") == off.get("pair_identity")
        if on.get("contract_version") or off.get("contract_version"):
            matched &= on.get("contract_version") == off.get("contract_version")
        if on.get("retrieval_config_identity") or off.get("retrieval_config_identity"):
            matched &= on.get("retrieval_config_identity") == off.get(
                "retrieval_config_identity"
            )
        if not matched:
            raise ProducerIntegrityError("unmatched graph ON/OFF pair")
        query_id = on.get("query_id")
        if not isinstance(query_id, str) or not query_id or query_id in query_ids:
            raise ProducerIntegrityError("B11 query identity is missing or duplicated")
        query_ids.add(query_id)
        if mesa_repo_sha and on.get("mesa_sha") != mesa_repo_sha:
            raise ProducerIntegrityError(
                f"B11 pair MESA SHA mismatch: {on.get('mesa_sha')} != {mesa_repo_sha}"
            )
        if pair.get("pair_identity") and pair.get("pair_identity") != on.get(
            "pair_identity"
        ):
            raise ProducerIntegrityError("B11 pair identity mismatch")
        scope_id = pair.get("scope_identity")
        if scope_id is not None and (
            not isinstance(scope_id, dict) or not scope_id.get("tenant_id")
        ):
            raise ProducerIntegrityError("B11 pair missing scope_identity")

        # Disallow graph paths or graph origins in OFF
        if off.get("paths"):
            raise ProducerIntegrityError("B11 OFF pair leaked graph paths")
        off_top5 = off.get("top5_origins", [])
        if any("graph" in origs for origs in off_top5 if isinstance(origs, list)):
            raise ProducerIntegrityError("B11 OFF pair leaked graph origins in top-5")

        paths = on.get("paths")
        provenance_valid &= (
            isinstance(paths, list)
            and bool(paths)
            and all(
                isinstance(graph_path, dict)
                and graph_path.get("graph_path_id")
                and graph_path.get("path_valid") is True
                for graph_path in paths
            )
        )
        pair_seen_paths: set[str] = set()
        if isinstance(paths, list):
            for graph_path in paths:
                if not isinstance(graph_path, dict):
                    continue
                stable_path_id = graph_path.get("graph_path_id")
                if stable_path_id in pair_seen_paths:
                    raise ProducerIntegrityError(
                        "duplicate graph path cannot amplify contribution"
                    )
                if isinstance(stable_path_id, str):
                    pair_seen_paths.add(stable_path_id)
        top5_origins = on.get("top5_origins")
        if (
            not isinstance(top5_origins, list)
            or len(top5_origins) > 5
            or any(
                not isinstance(origins, list)
                or any(not isinstance(origin, str) or not origin for origin in origins)
                for origins in top5_origins
            )
        ):
            raise ProducerIntegrityError("B11 top-5 origin evidence is malformed")
        if any("graph" in origins for origins in top5_origins) and paths:
            contribution += 1
        graph_operational &= (
            on.get("graph_backend_status") == "OPERATIONAL"
            and off.get("graph_backend_status") == "DISABLED_BY_NATIVE_SWITCH"
            and not on.get("graph_backend_error")
            and not off.get("graph_backend_error")
        )
        on_cov, off_cov = on.get("complete_evidence_at_5"), off.get(
            "complete_evidence_at_5"
        )
        on_rank, off_rank = on.get("first_relevant_rank"), off.get(
            "first_relevant_rank"
        )
        if (
            isinstance(on_cov, bool)
            or isinstance(off_cov, bool)
            or not isinstance(on_cov, (int, float))
            or not isinstance(off_cov, (int, float))
            or not 0 <= on_cov <= 1
            or not 0 <= off_cov <= 1
        ):
            raise ProducerIntegrityError("B11 evidence coverage is missing")
        if on_rank is not None and (not isinstance(on_rank, int) or on_rank < 1):
            raise ProducerIntegrityError("B11 ON rank is invalid")
        if off_rank is not None and (not isinstance(off_rank, int) or off_rank < 1):
            raise ProducerIntegrityError("B11 OFF rank is invalid")
        on_rank_key = on_rank if on_rank is not None else math.inf
        off_rank_key = off_rank if off_rank is not None else math.inf
        if on_cov > off_cov or (on_cov == off_cov and on_rank_key < off_rank_key):
            positive += 1
        elif on_cov < off_cov or (on_cov == off_cov and on_rank_key > off_rank_key):
            harm += 1
        else:
            neutral += 1

    return _completed(
        "B11",
        {
            "graph_capability_operational": graph_operational,
            "graph_causal_ablation_proven": positive > 0,
            "graph_provenance_verified": provenance_valid,
            "graph_rel_contribution_count": contribution,
            "graph_positive_utility_count": positive,
            "graph_neutral_effect_count": neutral,
            "graph_harm_count": harm,
        },
        raw_files,
        ctx,
    )


def _b12(ctx: ProducerContext) -> ProducerObservation:
    data, path = _score_summary(ctx)
    metrics = data.get("metrics")
    if (
        not isinstance(metrics, dict)
        or data.get("lane_status", {}).get("answers") != "PASS"
    ):
        raise ProducerIntegrityError("B12 answer population is incomplete")
    required = (
        "answerable_pass_rate",
        "no_answer_pass_rate",
        "unsupported_material_claim_rate",
        "fabricated_evidence_chunk_ids",
    )
    if any(metrics.get(key) is None for key in required):
        raise ProducerIntegrityError("B12 required measured population is empty")
    expected_population = {
        "answer_population": 80,
        "answerable_answer_population": 70,
        "no_answer_population": 10,
    }
    if any(metrics.get(key) != value for key, value in expected_population.items()):
        raise ProducerIntegrityError("B12 frozen TEST answer population is incomplete")
    return _completed("B12", {key: metrics[key] for key in required}, [path], ctx)


def _b13(ctx: ProducerContext) -> ProducerObservation:
    snapshots = []
    paths = []
    for name, phase in (
        ("health-pre-test.json", HealthPhase.PRE_TEST),
        ("health-post-test.json", HealthPhase.POST_TEST),
    ):
        data, path = _json(ctx, name)
        snapshot = HealthSnapshot.model_validate(data)
        if snapshot.phase is not phase:
            raise ProducerIntegrityError(f"wrong health phase in {name}")
        recomputed = capture_health_snapshot(
            run_id=ctx.run_id,
            phase=phase,
            timestamp_utc=snapshot.timestamp_utc,
            services=snapshot.services,
            provider_reachable=snapshot.provider_reachable,
            host_metrics=snapshot.host_metrics,
        )
        snapshots.append(recomputed)
        if not snapshot.host_metrics:
            raise ProducerIntegrityError(f"host metrics are missing in {name}")
        paths.append(path)
    samples, telemetry = _jsonl(ctx, "resource-telemetry.jsonl", ResourceSample)
    events, event_path = _jsonl(
        ctx, "resource-pressure-events.jsonl", ResourcePressureEvent
    )
    resource = evaluate_resource_status(samples, events)
    oom = sum(sample.oom_killed_count for sample in samples)
    catastrophic = int(
        resource["status"] != "PASS"
        or any(snapshot.status is not OperationalStatus.PASS for snapshot in snapshots)
    )
    return _completed(
        "B13",
        {
            "catastrophic_resource_failure": catastrophic,
            "oom_killed_count": oom,
            "resource_usage_recorded": bool(samples),
        },
        [*paths, telemetry, event_path],
        ctx,
    )


def _b14(ctx: ProducerContext) -> ProducerObservation:
    verification = verify_contract_freeze(
        ctx.freeze_path,
        ctx.checksum_path,
        repository_root=ctx.repository_root,
        current_repository_shas=ctx.current_repository_shas,
    )
    raw, raw_path = _json(ctx, "raw-manifest.json")
    oracle, oracle_path = _json(ctx, "oracle-leakage-audit.json")
    score, score_path = _score_summary(ctx)
    coherent = (
        verification.status is FreezeStatus.PASS
        and raw.get("manifest_hash") == ctx.raw_manifest_hash
        and oracle.get("raw_manifest_hash") == ctx.raw_manifest_hash
        and score.get("raw_manifest_hash") == ctx.raw_manifest_hash
        and oracle.get("status") == "PASS"
        and oracle.get("finding_count") == 0
    )
    return _completed(
        "B14",
        {
            "evidence_integrity_verified": coherent,
            "post_freeze_mutations": 0 if coherent else 1,
        },
        [raw_path, oracle_path, score_path],
        ctx,
    )


PRODUCTION_METRIC_PRODUCERS: dict[
    str, Callable[[ProducerContext], ProducerObservation]
] = {
    "B0": _b0,
    "B1": _b1,
    "B2": _b2,
    "B3": _b3,
    "B4": _b4,
    "B5": _b5,
    "B6": _b6,
    "B7": _b7,
    "B8": _b8,
    "B9": _b9,
    "B10": _b10,
    "B11": _b11,
    "B12": _b12,
    "B13": _b13,
    "B14": _b14,
}


def produce_all(ctx: ProducerContext) -> dict[str, ProducerObservation]:
    if set(PRODUCTION_METRIC_PRODUCERS) != PRODUCTION_GATE_IDS:
        raise ProducerIntegrityError("producer registry must contain exactly B0-B14")
    try:
        frozen_producer_code_sha256(ctx)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            gate_id: _blocked(
                gate_id, f"authoritative producer code is not frozen: {exc}"
            )
            for gate_id in PRODUCTION_METRIC_PRODUCERS
        }
    results: dict[str, ProducerObservation] = {}
    for gate_id, producer in PRODUCTION_METRIC_PRODUCERS.items():
        try:
            results[gate_id] = producer(ctx)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            results[gate_id] = _blocked(
                gate_id, f"authoritative evidence unavailable: {exc}"
            )
    return results
