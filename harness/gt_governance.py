"""Ground-truth structural validation and human audit workflow support."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from harness.identity import IdentityMap, UnknownIdentityError
from harness.models import GroundTruthItem, SHA256_PATTERN
from harness.normalizer import normalize_text, turkish_casefold


class GroundTruthValidationError(ValueError):
    pass


class QrelRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    query_class: str = Field(min_length=1)
    is_answerable: bool
    expected_source_chunk_ids: list[str] = Field(default_factory=list)
    evidence_groups: list[list[str]] = Field(default_factory=list)


class NoAnswerConclusion(str, Enum):
    NO_ANSWER_CONFIRMED = "NO_ANSWER_CONFIRMED"
    ANSWERABLE_RECLASSIFY = "ANSWERABLE_RECLASSIFY"
    UNRESOLVED = "UNRESOLVED"


class NoAnswerAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    query_id: str = Field(min_length=1)
    auditor: str = Field(min_length=1)
    reviewed_at_utc: datetime
    corpus_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    source_search_protocol: str = Field(min_length=1)
    searched_source_ids: list[str] = Field(min_length=1)
    conclusion: NoAnswerConclusion
    evidence_notes: str = Field(min_length=1)
    mesa_retrieval_used_as_authority: Literal[False]

    @field_validator("reviewed_at_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at_utc must be timezone-aware")
        return value


class DomainAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    query_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    reviewed_at_utc: datetime
    decision: Literal["APPROVE", "REJECT", "UNRESOLVED"]
    reviewed_source_ids: list[str] = Field(min_length=1)
    notes: str = Field(min_length=1)

    @field_validator("reviewed_at_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at_utc must be timezone-aware")
        return value


class HoldoutManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    holdout_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    class_distribution: dict[str, int]
    creation_protocol: str = Field(min_length=1)
    sealed_storage_reference: str = Field(min_length=1)
    lifecycle_status: Literal["PLANNED", "SEALED", "CONSUMED"]


def _load_jsonl(path: Path, model: type[BaseModel]) -> list[BaseModel]:
    records: list[BaseModel] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            records.append(model.model_validate_json(line))
        except ValidationError as exc:
            raise GroundTruthValidationError(
                f"{path}:{line_number}: {exc}"
            ) from exc
    return records


def load_ground_truth(path: str | Path) -> list[GroundTruthItem]:
    return [
        item
        for item in _load_jsonl(Path(path), GroundTruthItem)
        if isinstance(item, GroundTruthItem)
    ]


def _structural_errors(
    items: list[GroundTruthItem], identity_map: IdentityMap
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    for item in items:
        if item.query_id in seen_ids:
            errors.append(f"duplicate query_id: {item.query_id}")
        seen_ids.add(item.query_id)

        source_ids = set(item.expected_source_chunk_ids)
        for group in item.evidence_groups:
            if not group.acceptable_source_chunk_ids:
                errors.append(f"{item.query_id}: empty evidence group {group.group_id}")
            source_ids.update(group.acceptable_source_chunk_ids)
        for fact in item.required_facts:
            if not fact.supported_by:
                errors.append(f"{item.query_id}: fact {fact.fact_id} has empty supported_by")
            for span in fact.supported_by:
                if not span.exact_text.strip():
                    errors.append(
                        f"{item.query_id}: fact {fact.fact_id} has empty exact_text"
                    )
                source_ids.add(span.source_chunk_id)
                declared = set(item.expected_source_chunk_ids) | {
                    chunk_id
                    for group in item.evidence_groups
                    for chunk_id in group.acceptable_source_chunk_ids
                }
                if span.source_chunk_id not in declared:
                    errors.append(
                        f"{item.query_id}: fact {fact.fact_id} evidence is not declared"
                    )

        for source_id in sorted(source_ids):
            try:
                identity_map.resolve_source_chunk_id(source_id)
            except UnknownIdentityError:
                errors.append(f"{item.query_id}: unknown source ID {source_id}")

        if item.query_class == "RELATIONAL":
            if not item.is_answerable:
                errors.append(f"{item.query_id}: RELATIONAL item is not answerable")
            if len(item.evidence_groups) < 2:
                errors.append(f"{item.query_id}: RELATIONAL requires at least 2 groups")

        is_no_answer = item.query_class == "NO_ANSWER" or not item.is_answerable
        if is_no_answer:
            if item.query_class != "NO_ANSWER" or item.is_answerable:
                errors.append(f"{item.query_id}: inconsistent NO_ANSWER flags")
            if (
                item.expected_source_chunk_ids
                or item.evidence_groups
                or item.required_facts
            ):
                errors.append(f"{item.query_id}: NO_ANSWER contains positive oracle evidence")
        else:
            if not item.expected_source_chunk_ids:
                errors.append(f"{item.query_id}: answerable item has no expected evidence")
            if not item.required_facts:
                errors.append(f"{item.query_id}: answerable item has no required_facts")

        if item.required_facts and any(
            not pattern.fact_ids for pattern in item.acceptable_answer_patterns
        ):
            warnings.append(
                f"{item.query_id}: legacy answer pattern lacks explicit fact_ids"
            )
    return errors, warnings


def validate_ground_truth_items(
    items: list[GroundTruthItem], identity_map: IdentityMap, *, split_name: str
) -> dict[str, object]:
    errors, warnings = _structural_errors(items, identity_map)
    if errors:
        raise GroundTruthValidationError(
            f"{split_name} ground truth invalid: {'; '.join(errors)}"
        )
    return {
        "schema_version": "1.0",
        "split": split_name,
        "status": "PASS",
        "query_count": len(items),
        "errors": [],
        "warnings": warnings,
    }


def _normalized_groups(groups: Iterable[Iterable[str]]) -> list[list[str]]:
    return sorted(sorted(group) for group in groups)


def validate_ground_truth(
    gt_path: str | Path,
    qrels_path: str | Path,
    identity_map: IdentityMap,
    *,
    split_name: str,
) -> dict[str, object]:
    try:
        items = load_ground_truth(gt_path)
    except GroundTruthValidationError as exc:
        return {
            "schema_version": "1.0",
            "split": split_name,
            "status": "FAIL",
            "query_count": 0,
            "errors": [str(exc)],
            "warnings": [],
        }
    errors, warnings = _structural_errors(items, identity_map)
    try:
        qrels = [
            row
            for row in _load_jsonl(Path(qrels_path), QrelRow)
            if isinstance(row, QrelRow)
        ]
    except GroundTruthValidationError as exc:
        errors.append(str(exc))
        qrels = []

    gt_by_id = {item.query_id: item for item in items}
    qrel_by_id: dict[str, QrelRow] = {}
    for qrel in qrels:
        if qrel.query_id in qrel_by_id:
            errors.append(f"duplicate qrel query_id: {qrel.query_id}")
        qrel_by_id[qrel.query_id] = qrel
    for query_id in sorted(set(gt_by_id) | set(qrel_by_id)):
        item = gt_by_id.get(query_id)
        qrel = qrel_by_id.get(query_id)
        if item is None or qrel is None:
            errors.append(f"qrel/GT query set mismatch: {query_id}")
            continue
        if (
            qrel.query_class != item.query_class
            or qrel.is_answerable != item.is_answerable
            or set(qrel.expected_source_chunk_ids)
            != set(item.expected_source_chunk_ids)
            or _normalized_groups(qrel.evidence_groups)
            != _normalized_groups(
                group.acceptable_source_chunk_ids for group in item.evidence_groups
            )
        ):
            errors.append(f"qrel content mismatch: {query_id}")

    return {
        "schema_version": "1.0",
        "split": split_name,
        "status": "FAIL" if errors else "PASS",
        "query_count": len(items),
        "errors": errors,
        "warnings": warnings,
    }


def validate_dev_test_leakage(
    dev_items: list[GroundTruthItem], test_items: list[GroundTruthItem]
) -> dict[str, object]:
    dev_ids = {item.query_id for item in dev_items}
    test_ids = {item.query_id for item in test_items}
    dev_questions = {_normalized_question(item.question) for item in dev_items}
    test_questions = {_normalized_question(item.question) for item in test_items}
    dev_evidence = {
        source_id for item in dev_items for source_id in item.expected_source_chunk_ids
    }
    test_evidence = {
        source_id for item in test_items for source_id in item.expected_source_chunk_ids
    }
    overlaps = {
        "query_ids": sorted(dev_ids & test_ids),
        "questions": sorted(dev_questions & test_questions),
        "evidence_ids": sorted(dev_evidence & test_evidence),
    }
    return {
        "schema_version": "1.0",
        "status": "FAIL" if any(overlaps.values()) else "PASS",
        "overlaps": overlaps,
    }


def _normalized_question(question: str) -> str:
    return turkish_casefold(normalize_text(question))


def build_domain_audit_plan(
    items: list[GroundTruthItem], *, seed: str, single_fraction: float
) -> dict[str, object]:
    if not 0 <= single_fraction <= 1:
        raise ValueError("single_fraction must be between 0 and 1")
    relational = sorted(
        item.query_id for item in items if item.query_class == "RELATIONAL"
    )
    no_answer = sorted(
        item.query_id
        for item in items
        if item.query_class == "NO_ANSWER" or not item.is_answerable
    )
    single = [item.query_id for item in items if item.query_class.startswith("SINGLE_")]
    ranked_single = sorted(
        single,
        key=lambda query_id: hashlib.sha256(
            f"{seed}\0{query_id}".encode("utf-8")
        ).hexdigest(),
    )
    sample_size = math.ceil(len(single) * single_fraction)
    selected_single = sorted(ranked_single[:sample_size])
    return {
        "schema_version": "1.0",
        "status": "HUMAN_REVIEW_REQUIRED",
        "policy_status": "RECOMMENDATION_PENDING_HUMAN_APPROVAL",
        "seed": seed,
        "single_fraction": single_fraction,
        "selected_counts": {
            "NO_ANSWER": len(no_answer),
            "RELATIONAL": len(relational),
            "SINGLE": len(selected_single),
        },
        "selected_query_ids": sorted(relational + no_answer + selected_single),
    }


def build_domain_audit_artifact(
    plan: dict[str, object], records: list[DomainAuditRecord]
) -> dict[str, object]:
    selected = set(plan.get("selected_query_ids", []))
    observed = [record.query_id for record in records]
    duplicates = sorted(
        query_id for query_id in set(observed) if observed.count(query_id) > 1
    )
    missing = sorted(selected - set(observed))
    unexpected = sorted(set(observed) - selected)
    rejected = sorted(
        record.query_id for record in records if record.decision == "REJECT"
    )
    unresolved = sorted(
        record.query_id for record in records if record.decision == "UNRESOLVED"
    )
    if duplicates or unexpected or rejected:
        status = "FAIL"
    elif missing or unresolved:
        status = "HUMAN_REVIEW_REQUIRED"
    else:
        status = "PASS"
    return {
        "schema_version": "1.0",
        "status": status,
        "policy_status": plan.get("policy_status"),
        "seed": plan.get("seed"),
        "single_fraction": plan.get("single_fraction"),
        "selected_query_ids": sorted(selected),
        "duplicates": duplicates,
        "missing": missing,
        "unexpected": unexpected,
        "rejected": rejected,
        "unresolved": unresolved,
        "records": [
            record.model_dump(mode="json")
            for record in sorted(records, key=lambda item: item.query_id)
        ],
    }


def write_domain_audit_artifact(
    plan: dict[str, object], records: list[DomainAuditRecord], path: str | Path
) -> dict[str, object]:
    payload = build_domain_audit_artifact(plan, records)
    serialized = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    Path(path).write_text(serialized, encoding="utf-8", newline="\n")
    return payload


def validate_no_answer_audit(
    items: list[GroundTruthItem], records: list[NoAnswerAuditRecord]
) -> dict[str, object]:
    expected = {
        item.query_id
        for item in items
        if item.query_class == "NO_ANSWER" or not item.is_answerable
    }
    observed = [record.query_id for record in records]
    duplicates = sorted(
        query_id for query_id in set(observed) if observed.count(query_id) > 1
    )
    missing = sorted(expected - set(observed))
    unexpected = sorted(set(observed) - expected)
    unresolved = sorted(
        record.query_id
        for record in records
        if record.conclusion is not NoAnswerConclusion.NO_ANSWER_CONFIRMED
    )
    status = "PASS" if not (duplicates or missing or unexpected or unresolved) else "FAIL"
    return {
        "schema_version": "1.0",
        "status": status,
        "duplicates": duplicates,
        "missing": missing,
        "unexpected": unexpected,
        "unresolved": unresolved,
    }


def write_no_answer_audit_jsonl(
    records: list[NoAnswerAuditRecord], path: str | Path
) -> None:
    lines = [
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for record in sorted(records, key=lambda item: item.query_id)
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


FORBIDDEN_HOLDOUT_KEYS = {
    "qrel",
    "qrels",
    "query",
    "queries",
    "query_id",
    "question",
    "questions",
    "expected_answer",
    "required_facts",
    "gold_evidence_ids",
}


def _find_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.casefold() in FORBIDDEN_HOLDOUT_KEYS:
                return key
            found = _find_forbidden_key(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_forbidden_key(nested)
            if found:
                return found
    return None


def validate_holdout_manifest(payload: dict[str, Any]) -> dict[str, object]:
    forbidden = _find_forbidden_key(payload)
    if forbidden:
        raise GroundTruthValidationError(
            f"plaintext oracle field is forbidden in public holdout manifest: {forbidden}"
        )
    try:
        manifest = HoldoutManifest.model_validate(payload)
    except ValidationError as exc:
        raise GroundTruthValidationError(f"invalid holdout manifest: {exc}") from exc
    return {
        "schema_version": manifest.schema_version,
        "holdout_id": manifest.holdout_id,
        "status": "PASS",
        "lifecycle_status": manifest.lifecycle_status,
    }
