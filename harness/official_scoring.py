"""Frozen-authority raw-to-official-scorer production binding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.answer_scorer import score_answer
from harness.artifacts import (
    CertifiedAnswerExecutionCapture,
    RunArtifactStore,
    canonical_json_bytes,
)
from harness.gt_governance import load_ground_truth, validate_ground_truth
from harness.identity import IdentityMap
from harness.mesa_adapters import normalize_search_response
from harness.models import AnswerResponse, GroundTruthItem, ScoringStatus
from harness.normalizer import DEFAULT_NORMALIZATION_PATH, load_normalization_authority
from harness.retrieval_scorer import score_retrieval


class ScoringAuthorityUnavailable(RuntimeError):
    """The freeze does not identify every input needed for official scoring."""


class OfficialScoringError(RuntimeError):
    """A frozen input or sealed raw artifact failed an integrity invariant."""


@dataclass(frozen=True)
class FrozenScoringAuthority:
    run_id: str
    mesa_sha: str
    mesa_api_version: str
    ground_truth_path: Path
    ground_truth_sha256: str
    qrels_path: Path
    qrels_sha256: str
    identity_map_path: Path
    identity_map_sha256: str
    normalization_path: Path
    normalization_sha256: str
    scorer_sha256: str
    scorer_paths: tuple[Path, ...]
    answer_provider: str
    answer_model: str
    system_prompt_sha256: str
    answer_instruction_sha256: str
    request_parameters_sha256: str
    context_contract_version: str
    source_context_contract: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aggregate_hash(paths: tuple[Path, ...], root: Path) -> str:
    rows = [
        {
            "path": path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": _sha256(path),
        }
        for path in sorted(paths)
    ]
    return hashlib.sha256(canonical_json_bytes(rows)).hexdigest()


def load_frozen_scoring_authority(
    *, freeze_path: str | Path, repository_root: str | Path, run_id: str
) -> FrozenScoringAuthority:
    """Resolve explicit scoring paths only when they are hash-listed in freeze."""

    try:
        freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScoringAuthorityUnavailable(
            f"cannot read contract freeze: {exc}"
        ) from exc
    if freeze.get("run_id") != run_id:
        raise OfficialScoringError("contract freeze run_id mismatch")
    runtime = freeze.get("runtime_identities")
    authority = runtime.get("scoring_authority") if isinstance(runtime, dict) else None
    if not isinstance(authority, dict):
        raise ScoringAuthorityUnavailable(
            "runtime_identities.scoring_authority is absent from contract freeze"
        )
    answer_authority = (
        runtime.get("answer_authority") if isinstance(runtime, dict) else None
    )
    if not isinstance(answer_authority, dict):
        raise ScoringAuthorityUnavailable(
            "runtime_identities.answer_authority is absent from contract freeze"
        )
    required_answer = {
        "provider",
        "model",
        "system_prompt_sha256",
        "answer_instruction_sha256",
        "request_parameters_sha256",
        "context_contract_version",
        "source_context_contract",
    }
    missing_answer = sorted(required_answer - answer_authority.keys())
    if missing_answer:
        raise ScoringAuthorityUnavailable(
            f"answer authority is missing fields: {missing_answer}"
        )
    if any(
        not isinstance(answer_authority[field], str) or not answer_authority[field]
        for field in required_answer
    ):
        raise OfficialScoringError("answer authority fields must be non-empty strings")
    for field in (
        "system_prompt_sha256",
        "answer_instruction_sha256",
        "request_parameters_sha256",
    ):
        value = answer_authority[field]
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise OfficialScoringError(f"answer authority has invalid {field}")
    required = {
        "ground_truth_path",
        "qrels_path",
        "identity_map_path",
        "normalization_path",
        "mesa_api_version",
    }
    missing = sorted(required - authority.keys())
    if missing:
        raise ScoringAuthorityUnavailable(
            f"scoring authority is missing fields: {missing}"
        )
    root = Path(repository_root).resolve()
    materials = freeze.get("materials")
    if not isinstance(materials, list):
        raise OfficialScoringError("contract freeze materials are malformed")
    frozen_by_path: dict[str, tuple[str, str]] = {}
    for item in materials:
        if not isinstance(item, dict):
            raise OfficialScoringError("contract freeze material row is malformed")
        path, category, digest = (
            item.get("path"),
            item.get("category"),
            item.get("sha256"),
        )
        if not all(isinstance(value, str) for value in (path, category, digest)):
            raise OfficialScoringError("contract freeze material row has invalid types")
        frozen_by_path[path] = (category, digest)

    def resolve(field: str, category: str) -> tuple[Path, str]:
        rel = authority[field]
        if not isinstance(rel, str) or rel not in frozen_by_path:
            raise ScoringAuthorityUnavailable(f"{field} is not a frozen material path")
        frozen_category, digest = frozen_by_path[rel]
        if frozen_category != category:
            raise OfficialScoringError(
                f"{field} has category {frozen_category!r}, expected {category!r}"
            )
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise OfficialScoringError(f"{field} escapes repository root") from exc
        if not path.is_file() or _sha256(path) != digest:
            raise OfficialScoringError(f"{field} is missing or differs from freeze")
        return path, digest

    gt_path, gt_sha = resolve("ground_truth_path", "ground_truth")
    qrels_path, qrels_sha = resolve("qrels_path", "qrels")
    identity_path, identity_sha = resolve("identity_map_path", "identity_map")
    normalization_path, normalization_sha = resolve(
        "normalization_path", "normalization"
    )
    scorer_paths = tuple(
        (root / item["path"]).resolve()
        for item in materials
        if item.get("category") == "scorer_source"
    )
    scorer_relpaths = {path.relative_to(root).as_posix() for path in scorer_paths}
    required_scorers = {
        "harness/retrieval_scorer.py",
        "harness/answer_scorer.py",
        "harness/official_scoring.py",
    }
    if not required_scorers.issubset(scorer_relpaths):
        raise ScoringAuthorityUnavailable(
            f"frozen scorer_source is missing official sources: "
            f"{sorted(required_scorers - scorer_relpaths)}"
        )
    mesa_sha = freeze.get("repository_shas", {}).get("MESA")
    if not isinstance(mesa_sha, str):
        raise OfficialScoringError("frozen MESA SHA is missing")
    return FrozenScoringAuthority(
        run_id=run_id,
        mesa_sha=mesa_sha,
        mesa_api_version=str(authority["mesa_api_version"]),
        ground_truth_path=gt_path,
        ground_truth_sha256=gt_sha,
        qrels_path=qrels_path,
        qrels_sha256=qrels_sha,
        identity_map_path=identity_path,
        identity_map_sha256=identity_sha,
        normalization_path=normalization_path,
        normalization_sha256=normalization_sha,
        scorer_sha256=_aggregate_hash(scorer_paths, root),
        scorer_paths=scorer_paths,
        answer_provider=answer_authority["provider"],
        answer_model=answer_authority["model"],
        system_prompt_sha256=answer_authority["system_prompt_sha256"],
        answer_instruction_sha256=answer_authority["answer_instruction_sha256"],
        request_parameters_sha256=answer_authority["request_parameters_sha256"],
        context_contract_version=answer_authority["context_contract_version"],
        source_context_contract=answer_authority["source_context_contract"],
    )


def _retrieval_metrics(scores: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in scores if row["is_answerable"]]
    single = [row for row in answerable if row["query_class"].startswith("SINGLE_")]
    relational = [row for row in answerable if row["query_class"] == "RELATIONAL"]

    def mean(rows: list[dict[str, Any]], key: str) -> float | None:
        return sum(float(row[key]) for row in rows) / len(rows) if rows else None

    return {
        "retrieval_population": len(scores),
        "answerable_population": len(answerable),
        "single_hop_population": len(single),
        "rel_population": len(relational),
        "answerable_recall_at_5": mean(answerable, "recall_at_5"),
        "answerable_mrr": mean(answerable, "mrr"),
        "single_hop_recall_at_5": mean(single, "recall_at_5"),
        "rel_complete_evidence_at_5": mean(relational, "complete_evidence_at_5"),
    }


def _answer_metrics(scores: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in scores if row["is_answerable"]]
    no_answer = [row for row in scores if not row["is_answerable"]]

    def pass_rate(rows: list[dict[str, Any]]) -> float | None:
        return (
            sum(1 for row in rows if row["status"] == ScoringStatus.PASS.value)
            / len(rows)
            if rows
            else None
        )

    unsupported = sum(int(row["unsupported_material_claim_count"]) for row in scores)
    fabricated = sum(
        1
        for row in scores
        for reason in row.get("reasons", [])
        if "outside retrieved context" in reason
        or "unknown MESA/source chunk ID" in reason
    )
    return {
        "answer_population": len(scores),
        "answerable_answer_population": len(answerable),
        "no_answer_population": len(no_answer),
        "answerable_pass_rate": pass_rate(answerable),
        "no_answer_pass_rate": pass_rate(no_answer),
        "unsupported_material_claim_rate": (
            unsupported / len(answerable) if answerable else None
        ),
        "fabricated_evidence_chunk_ids": fabricated,
    }


def score_run_from_frozen_authority(
    *,
    store: RunArtifactStore,
    authority: FrozenScoringAuthority,
    raw_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score only sealed current-run raw artifacts against frozen authority."""

    identity_map = IdentityMap()
    identity_map.load_from_file(
        authority.identity_map_path, expected_sha256=authority.identity_map_sha256
    )
    default_normalization = load_normalization_authority(DEFAULT_NORMALIZATION_PATH)
    frozen_normalization = load_normalization_authority(
        authority.normalization_path,
        expected_sha256=authority.normalization_sha256,
    )
    if frozen_normalization.sha256 != default_normalization.sha256:
        raise OfficialScoringError(
            "frozen normalization differs from the normalization used by official scorers"
        )
    validation = validate_ground_truth(
        authority.ground_truth_path,
        authority.qrels_path,
        identity_map,
        split_name="TEST",
    )
    if validation["status"] != "PASS":
        raise OfficialScoringError(
            f"frozen GT/qrels validation failed: {validation['errors']}"
        )
    ground_truth = load_ground_truth(authority.ground_truth_path)
    gt_by_query: dict[str, GroundTruthItem] = {
        item.query_id: item for item in ground_truth
    }
    if len(gt_by_query) != len(ground_truth) or not gt_by_query:
        raise OfficialScoringError(
            "frozen TEST ground truth is empty or has duplicate query IDs"
        )

    retrieval_scores: list[dict[str, Any]] = []
    answer_scores: list[dict[str, Any]] = []
    retrieval_identities: dict[str, tuple[str, tuple[str, ...]]] = {}
    answer_identities: dict[str, tuple[str, tuple[str, ...]]] = {}
    raw_manifest = raw_manifest or store.compute_raw_manifest()
    provider_exchanges: dict[str, tuple[dict[str, Any], str]] = {}
    for entry in raw_manifest["entries"]:
        path = store.run_dir / entry["path"]
        store._verify_seal(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("lane") != "provider_exchange":
            continue
        query_id = payload.get("query_id")
        if payload.get("run_id") != store.run_id or query_id not in gt_by_query:
            raise OfficialScoringError(
                "provider exchange has invalid run/query identity"
            )
        if query_id in provider_exchanges:
            raise OfficialScoringError("duplicate provider exchange for answer query")
        request = payload.get("request")
        response = payload.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise OfficialScoringError(
                "provider exchange request/response is malformed"
            )
        if (
            payload.get("request_sha256")
            != hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        ):
            raise OfficialScoringError("provider exchange request hash mismatch")
        if (
            payload.get("response_sha256")
            != hashlib.sha256(canonical_json_bytes(response)).hexdigest()
        ):
            raise OfficialScoringError("provider exchange response hash mismatch")
        provider_exchanges[str(query_id)] = (payload, entry["sha256"])

    for entry in raw_manifest["entries"]:
        path = store.run_dir / entry["path"]
        store._verify_seal(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("run_id") != store.run_id:
            raise OfficialScoringError(f"raw artifact run_id mismatch: {entry['path']}")
        lane = payload.get("lane")
        if lane not in {"retrieval", "answers"}:
            continue
        query_id = payload.get("query_id")
        if query_id not in gt_by_query:
            raise OfficialScoringError(
                f"raw query_id is absent from frozen GT: {query_id}"
            )
        gt = gt_by_query[query_id]
        if lane == "retrieval":
            request_record = payload.get("request")
            response_record = payload.get("response")
            if not isinstance(request_record, dict) or not isinstance(
                response_record, dict
            ):
                raise OfficialScoringError(
                    "raw retrieval request/response wrapper is malformed"
                )
            request_payload = request_record.get("request")
            response_payload = response_record.get("response")
            if not isinstance(request_payload, dict) or not isinstance(
                response_payload, dict
            ):
                raise OfficialScoringError("raw retrieval payload is malformed")
            if (
                request_record.get("query_id") != query_id
                or response_record.get("query_id") != query_id
                or request_record.get("request_sha256")
                != hashlib.sha256(canonical_json_bytes(request_payload)).hexdigest()
                or response_record.get("response_sha256")
                != hashlib.sha256(canonical_json_bytes(response_payload)).hexdigest()
            ):
                raise OfficialScoringError(
                    "raw retrieval wrapper hash/identity mismatch"
                )
            if request_payload.get("query") != gt.question:
                raise OfficialScoringError(
                    "retrieval query differs from frozen GT question"
                )
            if request_payload.get("limit") != 5:
                raise OfficialScoringError(
                    "official retrieval request limit must equal 5"
                )
            request_datasets = request_payload.get("dataset_ids")
            if (
                not isinstance(request_datasets, list)
                or not request_datasets
                or len(request_datasets) != len(set(request_datasets))
                or any(
                    not isinstance(value, str) or not value
                    for value in request_datasets
                )
            ):
                raise OfficialScoringError(
                    "official retrieval dataset identity is invalid"
                )
            request_session = request_payload.get("session_id")
            if not isinstance(request_session, str) or not request_session:
                raise OfficialScoringError(
                    "official retrieval session identity is invalid"
                )
            retrieval_identities[str(query_id)] = (
                request_session,
                tuple(request_datasets),
            )
            status = response_record.get("transport_status")
            if not isinstance(status, int):
                raise OfficialScoringError("raw retrieval transport status is missing")
            if status != 200:
                score = score_retrieval(
                    gt, [], identity_map, is_infrastructure_error=True
                )
            else:
                capture = normalize_search_response(
                    run_id=store.run_id,
                    query_id=query_id,
                    request=request_payload,
                    response=response_payload,
                    api_version=authority.mesa_api_version,
                    mesa_sha=authority.mesa_sha,
                )
                scorer_results = [
                    {
                        "rank": result.rank,
                        "chunk_id": result.mesa_chunk_id,
                        "score": result.final_score,
                    }
                    for result in capture.results
                ]
                score = score_retrieval(gt, scorer_results, identity_map)
                if retrieval_identities[str(query_id)] != (
                    capture.session_id,
                    tuple(capture.dataset_ids),
                ):
                    raise OfficialScoringError(
                        "retrieval request/response scope identity mismatch"
                    )
            serialized = score.model_dump(mode="json")
            store.persist_scored(lane="retrieval", query_id=query_id, score=serialized)
            retrieval_scores.append(serialized)
        elif lane == "answers":
            try:
                capture = CertifiedAnswerExecutionCapture.model_validate(
                    {
                        key: value
                        for key, value in payload.items()
                        if key != "execution_id"
                    }
                )
            except Exception as exc:
                raise OfficialScoringError(
                    f"answer {query_id} is not an exact provider-boundary v2 capture"
                ) from exc
            if capture.mesa_sha != authority.mesa_sha:
                raise OfficialScoringError(
                    "answer capture MESA SHA differs from freeze"
                )
            if capture.question != gt.question:
                raise OfficialScoringError(
                    "answer question differs from frozen GT question"
                )
            request_parameters_sha256 = hashlib.sha256(
                canonical_json_bytes(capture.request_parameters)
            ).hexdigest()
            if (
                capture.provider != authority.answer_provider
                or capture.model != authority.answer_model
                or capture.system_prompt_sha256 != authority.system_prompt_sha256
                or capture.answer_instruction_sha256
                != authority.answer_instruction_sha256
                or request_parameters_sha256 != authority.request_parameters_sha256
                or capture.context_contract_version
                != authority.context_contract_version
                or capture.source_context_contract != authority.source_context_contract
            ):
                raise OfficialScoringError(
                    "answer provider/prompt/context identity differs from freeze"
                )
            exchange_row = provider_exchanges.get(str(query_id))
            if exchange_row is None:
                raise OfficialScoringError(
                    "answer capture has no sealed pre-parse provider exchange"
                )
            exchange, exchange_sha256 = exchange_row
            if (
                capture.provider_exchange_sha256 != exchange_sha256
                or exchange.get("provider") != capture.provider
                or exchange.get("request") != capture.exact_provider_request
                or exchange.get("response") != capture.raw_provider_response
            ):
                raise OfficialScoringError(
                    "answer capture differs from sealed pre-parse provider exchange"
                )
            answer = AnswerResponse.model_validate(capture.parsed_response)
            answer_identities[str(query_id)] = (
                capture.session_id,
                tuple(capture.dataset_ids),
            )
            score = score_answer(
                gt,
                answer,
                capture.context_evidence_ids,
                identity_map,
                exact_model_visible_context=capture.exact_model_visible_context,
            )
            serialized = score.model_dump(mode="json")
            store.persist_scored(lane="answers", query_id=query_id, score=serialized)
            answer_scores.append(serialized)
        else:
            raise OfficialScoringError(f"unknown raw scoring lane: {lane!r}")

    retrieval_ids = {row["query_id"] for row in retrieval_scores}
    answer_ids = {row["query_id"] for row in answer_scores}
    expected_ids = set(gt_by_query)
    for query_id in sorted(expected_ids & retrieval_ids & answer_ids):
        if retrieval_identities.get(query_id) != answer_identities.get(query_id):
            raise OfficialScoringError(
                f"retrieval/answer session or dataset identity mismatch: {query_id}"
            )
    if len(retrieval_ids) != len(retrieval_scores) or len(answer_ids) != len(
        answer_scores
    ):
        raise OfficialScoringError("duplicate query in a scored lane")
    retrieval_metrics = _retrieval_metrics(retrieval_scores)
    answer_metrics = _answer_metrics(answer_scores)
    retrieval_complete = retrieval_ids == expected_ids
    answer_complete = answer_ids == expected_ids
    integrity_failures = {
        ScoringStatus.MAPPING_INTEGRITY_ERROR.value,
        ScoringStatus.INFRASTRUCTURE_ERROR.value,
    }
    scoring_integrity_pass = not any(
        row["status"] in integrity_failures
        for row in [*retrieval_scores, *answer_scores]
    )
    common = {
        "schema_version": "2.0",
        "run_id": store.run_id,
        "scorer_version": "profile-b-official-v2",
        "scorer_sha256": authority.scorer_sha256,
        "ground_truth_sha256": authority.ground_truth_sha256,
        "qrels_sha256": authority.qrels_sha256,
        "identity_map_sha256": authority.identity_map_sha256,
        "normalization_sha256": authority.normalization_sha256,
        "raw_manifest_hash": raw_manifest["manifest_hash"],
    }
    retrieval_report = {
        **common,
        "lane": "retrieval",
        "status": "PASS" if retrieval_complete and scoring_integrity_pass else "FAIL",
        "population_complete": retrieval_complete,
        "expected_query_count": len(expected_ids),
        "item_count": len(retrieval_scores),
        "metrics": retrieval_metrics,
        "items": retrieval_scores,
    }
    answer_report = {
        **common,
        "lane": "answers",
        "status": "PASS" if answer_complete and scoring_integrity_pass else "FAIL",
        "population_complete": answer_complete,
        "expected_query_count": len(expected_ids),
        "item_count": len(answer_scores),
        "metrics": answer_metrics,
        "items": answer_scores,
    }
    return {
        **common,
        "status": (
            "PASS"
            if retrieval_report["status"] == answer_report["status"] == "PASS"
            else "FAIL"
        ),
        "item_count": len(retrieval_scores) + len(answer_scores),
        "retrieval": retrieval_report,
        "answers": answer_report,
    }
