"""Tests for the authoritative Profile B VM Qualification Runner."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.qualification_runner import (
    QualificationConfig,
    QualificationResult,
    QualificationRunnerError,
    run_profile_b_qualification,
)
from harness.scope_collector import ScopeTestCase
from tests.test_phase7_scope_collector import _mock_mesa_response
from tests.test_phase8_9_graph_and_state_proof import _mock_graph_executor, _setup_mock_stores


ROOT = Path(__file__).resolve().parents[1]
MESA_SHA = "a" * 40
DATA_SHA = "b" * 40
CERT_SHA = "c" * 40


def _setup_test_repo(tmp_path: Path, run_id: str = "RUN-QUAL-TEST") -> tuple[Path, Path, Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    freeze_dir = repo / "freeze"
    freeze_dir.mkdir(parents=True, exist_ok=True)

    materials: dict[str, list[Path]] = {}
    for cat in sorted(MANDATORY_MATERIAL_CATEGORIES):
        p = freeze_dir / f"{cat}.txt"
        p.write_text(cat, encoding="utf-8")
        materials[cat] = [p]

    gt = repo / "ground-truth" / "test.jsonl"
    gt.parent.mkdir(parents=True, exist_ok=True)
    gt.write_text(
        json.dumps(
            {
                "query_id": "Q-1",
                "query_class": "SINGLE_DIRECT",
                "question": "Question?",
                "expected_source_chunk_ids": ["source-chunk-1"],
                "evidence_groups": [
                    {
                        "group_id": "G1",
                        "acceptable_source_chunk_ids": ["source-chunk-1"],
                    }
                ],
                "required_facts": [
                    {
                        "fact_id": "F1",
                        "claim": "Exact legal fact",
                        "supported_by": [
                            {
                                "source_chunk_id": "source-chunk-1",
                                "span_id": "S1",
                                "exact_text": "Exact legal fact",
                            }
                        ],
                    }
                ],
                "acceptable_answer_patterns": [
                    {"mode": "literal", "value": "Exact legal fact", "fact_ids": ["F1"]}
                ],
                "forbidden_claims": [],
                "is_answerable": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    materials["ground_truth"] = [gt]

    qrels = repo / "ground-truth" / "qrels.jsonl"
    qrels.write_text(
        json.dumps(
            {
                "query_id": "Q-1",
                "query_class": "SINGLE_DIRECT",
                "is_answerable": True,
                "expected_source_chunk_ids": ["source-chunk-1"],
                "evidence_groups": [["source-chunk-1"]],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    materials["qrels"] = [qrels]

    identity = repo / "ground-truth" / "identity-map.jsonl"
    identity.write_text(
        json.dumps(
            {
                "mesa_chunk_id": "mesa-chunk-1",
                "source_chunk_id": "source-chunk-1",
                "content_hash": "1" * 64,
                "delivery_state": "COMMITTED",
                "document_id": "document-1",
                "remote_mutation_id": "mutation-1",
                "version_id": "revision-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    materials["identity_map"] = [identity]

    normalization = repo / "config" / "scoring-normalization.json"
    normalization.parent.mkdir(parents=True, exist_ok=True)
    normalization.write_text((ROOT / "config" / "scoring-normalization.json").read_text(encoding="utf-8"), encoding="utf-8")
    materials["normalization"] = [normalization]

    # Required harness source files
    harness_dir = repo / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    harness_files = []
    for name in (
        "metric_producers.py", "gates.py", "transaction.py",
        "scope_collector.py", "graph_collector.py", "state_proof.py",
        "mesa_adapters.py", "qualification_runner.py", "finalizer.py",
    ):
        dest = harness_dir / name
        dest.write_text((ROOT / "harness" / name).read_text(encoding="utf-8"), encoding="utf-8")
        harness_files.append(dest)
    materials["harness_source"] = harness_files

    scorer_dir = repo / "harness"
    scorer_files = []
    for name in ("retrieval_scorer.py", "answer_scorer.py", "official_scoring.py"):
        dest = scorer_dir / name
        dest.write_text((ROOT / "harness" / name).read_text(encoding="utf-8"), encoding="utf-8")
        scorer_files.append(dest)
    materials["scorer_source"] = scorer_files

    gate_config = repo / "config" / "profile-b-gates.json"
    gate_config.parent.mkdir(parents=True, exist_ok=True)
    gate_config.write_text((ROOT / "config" / "profile-b-gates.json").read_text(encoding="utf-8"), encoding="utf-8")
    materials["thresholds"] = [gate_config]

    shas = {
        "MESA": MESA_SHA,
        "MESA_Data": DATA_SHA,
        "MESA_E2E_Certification": CERT_SHA,
    }
    freeze_path, checksum_path = create_contract_freeze(
        output_dir=freeze_dir,
        run_id=run_id,
        repository_root=repo,
        repository_shas=shas,
        material_paths=materials,
        runtime_identities={
            "python": "3.13.12",
            "answer_authority": {
                "provider": "openai_compatible",
                "model": "openai/gpt-oss-20b",
                "system_prompt_sha256": "0" * 64,
                "answer_instruction_sha256": "0" * 64,
                "request_parameters_sha256": "0" * 64,
                "context_contract_version": "mesa-e2e.context.v1",
                "source_context_contract": "GET /v4/sessions/{session_id}/context",
            },
            "scoring_authority": {
                "ground_truth_path": gt.relative_to(repo).as_posix(),
                "qrels_path": qrels.relative_to(repo).as_posix(),
                "identity_map_path": identity.relative_to(repo).as_posix(),
                "normalization_path": normalization.relative_to(repo).as_posix(),
                "mesa_api_version": "v4",
            },
        },
    )

    stores_dir = tmp_path / "stores"
    stores_dir.mkdir(parents=True, exist_ok=True)
    sql, lance, kuzu = _setup_mock_stores(stores_dir)
    return repo, freeze_path, checksum_path, sql, lance, kuzu


def test_qualification_runner_rejects_missing_or_empty_run_id(tmp_path: Path) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    config = QualificationConfig(
        run_id="",
        run_dir=tmp_path / "run",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={"MESA": MESA_SHA, "MESA_Data": DATA_SHA, "MESA_E2E_Certification": CERT_SHA},
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
    )
    with pytest.raises(QualificationRunnerError, match="run_id must be non-empty"):
        run_profile_b_qualification(config)


def test_qualification_runner_rejects_missing_freeze(tmp_path: Path) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    config = QualificationConfig(
        run_id="RUN-TEST",
        run_dir=tmp_path / "run",
        freeze_path=tmp_path / "nonexistent-freeze.json",
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={"MESA": MESA_SHA, "MESA_Data": DATA_SHA, "MESA_E2E_Certification": CERT_SHA},
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
    )
    with pytest.raises(QualificationRunnerError, match="freeze_path missing"):
        run_profile_b_qualification(config)


def test_qualification_runner_rejects_unresolved_repository_shas(tmp_path: Path) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    config = QualificationConfig(
        run_id="RUN-TEST",
        run_dir=tmp_path / "run",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={"MESA": "short", "MESA_Data": DATA_SHA, "MESA_E2E_Certification": CERT_SHA},
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
    )
    with pytest.raises(QualificationRunnerError, match="unresolved repository identity"):
        run_profile_b_qualification(config)


def test_qualification_runner_rejects_missing_stores(tmp_path: Path) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    config = QualificationConfig(
        run_id="RUN-TEST",
        run_dir=tmp_path / "run",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={"MESA": MESA_SHA, "MESA_Data": DATA_SHA, "MESA_E2E_Certification": CERT_SHA},
        sqlite_path=tmp_path / "missing.db",
        lancedb_dir=lance,
        kuzu_dir=kuzu,
    )
    with pytest.raises(QualificationRunnerError, match="SQLite store not found"):
        run_profile_b_qualification(
            config,
            mesa_scope_executor=lambda case: {},
            mesa_graph_executor=lambda mode, req: {},
        )


def test_qualification_runner_rejects_unquiescent_preconditions(tmp_path: Path) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    config = QualificationConfig(
        run_id="RUN-TEST",
        run_dir=tmp_path / "run",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={"MESA": MESA_SHA, "MESA_Data": DATA_SHA, "MESA_E2E_Certification": CERT_SHA},
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
        quiescence_evidence={"workers_stopped_or_read_only": False, "queues_drained": False},
    )
    with pytest.raises(QualificationRunnerError, match="BLOCKED_BY_RUNTIME_STATE_PROOF: quiescence preconditions failed"):
        run_profile_b_qualification(
            config,
            mesa_scope_executor=lambda case: {},
            mesa_graph_executor=lambda mode, req: {},
        )


def test_qualification_runner_executes_pipeline_with_authoritative_evidence(tmp_path: Path) -> None:
    run_id = "RUN-CANONICAL-01"
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path, run_id=run_id)
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    def scope_executor(case: ScopeTestCase) -> dict:
        return _mock_mesa_response(case, leak=False)

    def search_executor(req: dict) -> dict:
        matched = {
            "assertion_id": "assertion-1",
            "tenant_id": "tenant-1",
            "dataset_id": "dataset-1",
            "document_id": "document-1",
            "revision_id": "revision-1",
            "chunk_id": "mesa-chunk-1",
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "valid_from": "",
            "valid_to": "",
        }
        return {
            "session_id": req.get("session_id", "session-1"),
            "dataset_ids": req.get("dataset_ids", ["dataset-1"]),
            "results": [
                {
                    "candidate_id": "assertion-1",
                    "evidence_id": "assertion-1",
                    "assertion_id": "assertion-1",
                    "source_chunk_id": "mesa-chunk-1",
                    "document_id": "document-1",
                    "evidence_span": "Exact legal fact",
                    "raw_score": 0.1,
                    "rrf_score": 0.2,
                    "final_score": 0.2,
                    "provenance": [matched],
                    "matched_assertions": [matched],
                    "supporting_assertions": [],
                    "retrieval_provenance": {
                        "origins": ["vector"],
                        "lane_ranks": {"vector": 1},
                        "raw_scores": {"vector": 0.1},
                    },
                }
            ],
        }

    config = QualificationConfig(
        run_id=run_id,
        run_dir=run_dir,
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={"MESA": MESA_SHA, "MESA_Data": DATA_SHA, "MESA_E2E_Certification": CERT_SHA},
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
        gate_config_path=repo / "config" / "profile-b-gates.json",
        quiescence_evidence={"runtime_freeze_verified": True},
    )

    result = run_profile_b_qualification(
        config,
        mesa_scope_executor=scope_executor,
        mesa_graph_executor=_mock_graph_executor,
        mesa_search_executor=search_executor,
    )

    assert isinstance(result, QualificationResult)
    assert result.run_id == run_id
    assert (run_dir / "raw-manifest.json").is_file()
    assert (run_dir / "scope-isolation.json").is_file()
    assert (run_dir / "graph-ablation.json").is_file()
    assert (run_dir / "raw" / "state" / "state-proof.json").is_file()
