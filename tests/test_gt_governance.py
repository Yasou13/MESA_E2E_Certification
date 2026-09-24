from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.gt_governance import (
    DomainAuditRecord,
    GroundTruthValidationError,
    NoAnswerAuditRecord,
    NoAnswerConclusion,
    build_domain_audit_plan,
    build_domain_audit_artifact,
    load_ground_truth,
    validate_dev_test_leakage,
    validate_ground_truth,
    validate_ground_truth_items,
    validate_holdout_manifest,
    validate_no_answer_audit,
)
from harness.identity import IdentityMap
from harness.models import EvidenceGroup, ExactSourceSpan, GroundTruthItem, RequiredFact


REPOSITORY = Path(__file__).resolve().parents[1]
RUN_DIR = REPOSITORY / "runs" / "RUN-20260901T005200Z-p8b03"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def historical_identity_map() -> IdentityMap:
    mapping = IdentityMap()
    mapping.load_from_file(RUN_DIR / "identity_map.jsonl")
    return mapping


def test_historical_gt_and_qrels_are_structurally_valid(
    historical_identity_map: IdentityMap,
) -> None:
    test_report = validate_ground_truth(
        RUN_DIR / "ground-truth-test.jsonl",
        RUN_DIR / "qrels-test.jsonl",
        historical_identity_map,
        split_name="TEST",
    )
    dev_report = validate_ground_truth(
        RUN_DIR / "ground-truth-dev.jsonl",
        RUN_DIR / "qrels-dev.jsonl",
        historical_identity_map,
        split_name="DEV",
    )
    leakage = validate_dev_test_leakage(
        load_ground_truth(RUN_DIR / "ground-truth-dev.jsonl"),
        load_ground_truth(RUN_DIR / "ground-truth-test.jsonl"),
    )

    assert test_report["status"] == "PASS"
    assert test_report["query_count"] == 80
    assert dev_report["status"] == "PASS"
    assert dev_report["query_count"] == 12
    assert leakage["status"] == "PASS"


def test_structural_validator_rejects_duplicates_bad_sources_and_qrel_drift(
    tmp_path: Path,
) -> None:
    mapping = IdentityMap()
    mapping.add_mapping("M-1", "S-1")
    gt_path = tmp_path / "gt.jsonl"
    qrel_path = tmp_path / "qrels.jsonl"
    row = {
        "query_id": "Q-1",
        "query_class": "SINGLE_DIRECT",
        "question": "question",
        "expected_source_chunk_ids": ["S-UNKNOWN"],
        "evidence_groups": [
            {"group_id": "g1", "acceptable_source_chunk_ids": ["S-UNKNOWN"]}
        ],
        "required_facts": [
            {"fact_id": "f1", "claim": "claim", "supported_by": []}
        ],
        "acceptable_answer_patterns": ["claim"],
        "is_answerable": True,
    }
    gt_path.write_text(
        "\n".join(json.dumps(row) for _ in range(2)) + "\n", encoding="utf-8"
    )
    qrel_path.write_text(
        json.dumps(
            {
                "query_id": "Q-1",
                "query_class": "RELATIONAL",
                "is_answerable": True,
                "expected_source_chunk_ids": ["S-1"],
                "evidence_groups": [["S-1"]],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = validate_ground_truth(
        gt_path, qrel_path, mapping, split_name="TEST"
    )

    assert report["status"] == "FAIL"
    joined = "\n".join(report["errors"])
    assert "duplicate query_id" in joined
    assert "unknown" in joined
    assert "supported_by" in joined
    assert "qrel" in joined


def test_rel_and_no_answer_schema_fail_closed() -> None:
    mapping = IdentityMap()
    mapping.add_mapping("M-1", "S-1")
    relational = GroundTruthItem(
        query_id="REL-1",
        query_class="RELATIONAL",
        question="question",
        expected_source_chunk_ids=["S-1"],
        evidence_groups=[
            EvidenceGroup(group_id="g1", acceptable_source_chunk_ids=["S-1"])
        ],
        required_facts=[
            RequiredFact(
                fact_id="f1",
                claim="claim",
                supported_by=[ExactSourceSpan(source_chunk_id="S-1", exact_text="claim")],
            )
        ],
    )
    invalid_no_answer = GroundTruthItem(
        query_id="NA-1",
        query_class="NO_ANSWER",
        question="question",
        expected_source_chunk_ids=["S-1"],
        is_answerable=False,
    )

    with pytest.raises(GroundTruthValidationError):
        validate_ground_truth_items(
            [relational, invalid_no_answer], mapping, split_name="TEST"
        )


def test_domain_audit_plan_is_deterministic_and_does_not_self_approve() -> None:
    items = load_ground_truth(RUN_DIR / "ground-truth-test.jsonl")
    first = build_domain_audit_plan(items, seed="profile-b-v2", single_fraction=0.2)
    second = build_domain_audit_plan(items, seed="profile-b-v2", single_fraction=0.2)

    assert first == second
    assert first["status"] == "HUMAN_REVIEW_REQUIRED"
    assert first["selected_counts"] == {
        "NO_ANSWER": 10,
        "RELATIONAL": 10,
        "SINGLE": 12,
    }
    incomplete = build_domain_audit_artifact(first, [])
    assert incomplete["status"] == "HUMAN_REVIEW_REQUIRED"
    tracked = json.loads(
        (
            REPOSITORY
            / "reports"
            / "qualification"
            / "RUN-20260901T005200Z-p8b03"
            / "gt-domain-audit-plan.json"
        ).read_text(encoding="utf-8")
    )
    assert tracked == first


def test_no_answer_audit_is_source_first_and_covers_every_negative() -> None:
    item = GroundTruthItem(
        query_id="NA-1",
        query_class="NO_ANSWER",
        question="question",
        is_answerable=False,
    )
    record = NoAnswerAuditRecord(
        query_id="NA-1",
        auditor="domain-reviewer",
        reviewed_at_utc=NOW,
        corpus_manifest_sha256="a" * 64,
        source_search_protocol="Search approved canonical source inventory",
        searched_source_ids=["source-1"],
        conclusion=NoAnswerConclusion.NO_ANSWER_CONFIRMED,
        evidence_notes="No governing source found in the frozen corpus.",
        mesa_retrieval_used_as_authority=False,
    )
    report = validate_no_answer_audit([item], [record])
    assert report["status"] == "PASS"

    with pytest.raises(ValueError):
        NoAnswerAuditRecord(
            **{
                **record.model_dump(),
                "mesa_retrieval_used_as_authority": True,
            }
        )


def test_holdout_manifest_forbids_plaintext_oracle_material() -> None:
    valid = {
        "schema_version": "1.0",
        "holdout_id": "sealed-profile-b-v2",
        "manifest_sha256": "a" * 64,
        "class_distribution": {"SINGLE_DIRECT": 40, "NO_ANSWER": 10},
        "creation_protocol": "independent source-first authoring",
        "sealed_storage_reference": "vault://profile-b-v2",
        "lifecycle_status": "SEALED",
    }
    assert validate_holdout_manifest(valid)["status"] == "PASS"

    with pytest.raises(GroundTruthValidationError, match="plaintext oracle"):
        validate_holdout_manifest({**valid, "qrels": [{"query_id": "secret"}]})
