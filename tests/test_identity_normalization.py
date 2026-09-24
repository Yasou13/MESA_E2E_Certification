from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness.identity import (
    ConflictingMappingError,
    DuplicateMappingError,
    IdentityHashMismatchError,
    IdentityMap,
    IdentityMapValidationError,
    UnknownIdentityError,
)
from harness.normalizer import (
    get_abstention_marker,
    load_normalization_authority,
    normalize_article_id,
    normalize_law_id,
    normalize_text,
)
from harness.answer_scorer import score_answer
from harness.models import AnswerResponse, GroundTruthItem
from harness.retrieval_scorer import score_retrieval


REPOSITORY = Path(__file__).resolve().parents[1]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> str:
    data = b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        for row in rows
    )
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_identity_load_is_strict_and_binary_hash_is_frozen(tmp_path: Path) -> None:
    path = tmp_path / "identity.jsonl"
    expected_hash = _write_jsonl(
        path,
        [{"mesa_chunk_id": "M-1", "source_chunk_id": "S-1"}],
    )
    identity_map = IdentityMap()
    identity_map.load_from_file(path, expected_sha256=expected_hash)

    assert identity_map.map_sha256 == expected_hash
    assert identity_map.resolve_source_chunk_id("M-1") == "S-1"
    assert identity_map.resolve_source_chunk_id("S-1") == "S-1"

    with pytest.raises(IdentityHashMismatchError):
        IdentityMap().load_from_file(path, expected_sha256="0" * 64)


def test_identity_rejects_conflicts_duplicates_unknowns_and_bad_rows(
    tmp_path: Path,
) -> None:
    conflict = tmp_path / "conflict.jsonl"
    _write_jsonl(
        conflict,
        [
            {"mesa_chunk_id": "M-1", "source_chunk_id": "S-1"},
            {"mesa_chunk_id": "M-1", "source_chunk_id": "S-2"},
        ],
    )
    with pytest.raises(ConflictingMappingError):
        IdentityMap().load_from_file(conflict)

    duplicate = tmp_path / "duplicate.jsonl"
    row = {"mesa_chunk_id": "M-1", "source_chunk_id": "S-1"}
    _write_jsonl(duplicate, [row, row])
    with pytest.raises(DuplicateMappingError):
        IdentityMap().load_from_file(duplicate)

    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text('{"mesa_chunk_id": "M-1"}\n', encoding="utf-8")
    with pytest.raises(IdentityMapValidationError):
        IdentityMap().load_from_file(malformed)

    identity_map = IdentityMap()
    identity_map.add_mapping("M-1", "S-1")
    with pytest.raises(UnknownIdentityError):
        identity_map.resolve_source_chunk_id("M-UNKNOWN")


def test_identity_validation_artifact_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "identity.jsonl"
    _write_jsonl(source, [{"mesa_chunk_id": "M-1", "source_chunk_id": "S-1"}])
    identity_map = IdentityMap()
    identity_map.load_from_file(source)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    identity_map.write_validation_artifact(first, source_path="identity.jsonl")
    identity_map.write_validation_artifact(second, source_path="identity.jsonl")

    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8"))["status"] == "PASS"


def test_normalization_config_is_the_runtime_authority(tmp_path: Path) -> None:
    source = REPOSITORY / "config" / "scoring-normalization.json"
    config = json.loads(source.read_text(encoding="utf-8"))
    config["abstention"]["expected_answer_marker"] = "KANIT YOK"
    config["identifiers"]["law_number_patterns"] = [r"^LAW-(\d+)$"]
    custom = tmp_path / "normalization.json"
    custom.write_text(
        json.dumps(config, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    authority = load_normalization_authority(custom)

    assert get_abstention_marker(authority) == "KANIT YOK"
    assert normalize_law_id("LAW-4857", authority) == "4857"
    assert normalize_law_id("4857 sayılı Kanun", authority) == "4857 sayılı Kanun"
    assert normalize_text("  A   B  ", authority) == "A B"


def test_normalization_hash_assertion_and_repository_fixtures() -> None:
    path = REPOSITORY / "config" / "scoring-normalization.json"
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    authority = load_normalization_authority(path, expected_sha256=expected)

    assert authority.sha256 == expected
    assert authority.version == "v1.0-turkish-legal-nfc"
    assert normalize_law_id("Kanun No: 4857", authority) == "4857"
    assert normalize_article_id("Madde 14", authority) == "madde-14"
    assert normalize_article_id("14. madde", authority) == "madde-14"

    with pytest.raises(ValueError, match="normalization SHA-256 mismatch"):
        load_normalization_authority(path, expected_sha256="0" * 64)


def test_scorers_surface_unknown_identity_instead_of_product_miss() -> None:
    identity_map = IdentityMap()
    identity_map.add_mapping("M-1", "S-1")
    gt = GroundTruthItem(
        query_id="Q-1",
        query_class="SINGLE_DIRECT",
        question="question",
        expected_source_chunk_ids=["S-1"],
        acceptable_answer_patterns=["answer"],
    )

    retrieval = score_retrieval(gt, [{"chunk_id": "M-UNKNOWN"}], identity_map)
    answer = score_answer(
        gt,
        AnswerResponse(answer="answer", evidence_chunk_ids=["M-UNKNOWN"]),
        ["M-1"],
        identity_map,
    )

    assert retrieval.status == "MAPPING_INTEGRITY_ERROR"
    assert answer.status == "MAPPING_INTEGRITY_ERROR"
