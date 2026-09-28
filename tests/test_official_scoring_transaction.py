from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.answer_execution import execute_answer_and_persist
from harness.artifacts import RunArtifactStore
from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.mesa_adapters import normalize_context_response
from harness.metric_producers import write_sealed_measurement
from harness.models import GateStatus
from harness.transaction import CertificationTransaction, TransactionError

RUN_ID = "RUN-official-scoring"
NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
MESA_SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[1]


class _Transport:
    provider_name = "openai_compatible"

    def __init__(self, *, cited_id="mesa-chunk-1"):
        self.cited_id = cited_id

    def complete(self, request_payload):
        return {
            "id": "provider-1",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": "Exact legal fact",
                                "evidence_chunk_ids": [self.cited_id],
                                "insufficient_evidence": False,
                                "claims": [
                                    {
                                        "fact_ids": ["F1"],
                                        "text": "Exact legal fact",
                                        "evidence_chunk_ids": [self.cited_id],
                                    }
                                ],
                            }
                        )
                    }
                }
            ],
        }


def _write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _authority_freeze(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    gt = _write(
        repo / "ground-truth" / "test.jsonl",
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
    )
    qrels = _write(
        repo / "ground-truth" / "qrels.jsonl",
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
    )
    identity = _write(
        repo / "ground-truth" / "identity-map.jsonl",
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
        + "\n"
        + json.dumps(
            {
                "mesa_chunk_id": "mesa-chunk-2",
                "source_chunk_id": "source-chunk-2",
                "content_hash": "2" * 64,
                "delivery_state": "COMMITTED",
                "document_id": "document-2",
                "remote_mutation_id": "mutation-2",
                "version_id": "revision-2",
            }
        )
        + "\n",
    )
    normalization = repo / "config" / "scoring-normalization.json"
    normalization.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "config" / "scoring-normalization.json", normalization)
    scorer_files = []
    for name in ("retrieval_scorer.py", "answer_scorer.py", "official_scoring.py"):
        destination = repo / "harness" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "harness" / name, destination)
        scorer_files.append(destination)
    producer_files = []
    for name in (
        "answer_execution.py",
        "artifacts.py",
        "execution_provenance.py",
        "metric_producers.py",
        "gates.py",
        "transaction.py",
        "scope_collector.py",
        "graph_collector.py",
        "state_proof.py",
        "mesa_adapters.py",
        "mesa_transport.py",
        "qualification_runner.py",
        "finalizer.py",
        "verdict.py",
    ):
        destination = repo / "harness" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "harness" / name, destination)
        producer_files.append(destination)
    gate_config = repo / "config" / "profile-b-gates.json"
    gate_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "config" / "profile-b-gates.json", gate_config)

    materials: dict[str, list[Path]] = {}
    for category in sorted(MANDATORY_MATERIAL_CATEGORIES):
        if category == "ground_truth":
            materials[category] = [gt]
        elif category == "qrels":
            materials[category] = [qrels]
        elif category == "identity_map":
            materials[category] = [identity]
        elif category == "normalization":
            materials[category] = [normalization]
        elif category == "scorer_source":
            materials[category] = scorer_files
        elif category == "harness_source":
            materials[category] = producer_files
        elif category == "thresholds":
            materials[category] = [gate_config]
        else:
            materials[category] = [
                _write(repo / "frozen" / f"{category}.txt", category)
            ]
    # scorer_source is already mandatory, but keep this explicit if the set evolves.
    materials["scorer_source"] = scorer_files
    shas = {
        "MESA": MESA_SHA,
        "MESA_Data": "b" * 40,
        "MESA_E2E_Certification": "c" * 40,
    }
    freeze_path, checksum_path = create_contract_freeze(
        output_dir=repo / "freeze",
        run_id=RUN_ID,
        repository_root=repo,
        repository_shas=shas,
        material_paths=materials,
        runtime_identities={
            "python": "3.10",
            "answer_authority": {
                "provider": "openai_compatible",
                "model": "openai/gpt-oss-20b",
                "system_prompt_sha256": hashlib.sha256(
                    b"Use only evidence"
                ).hexdigest(),
                "answer_instruction_sha256": hashlib.sha256(
                    b"Return structured answer"
                ).hexdigest(),
                "request_parameters_sha256": hashlib.sha256(
                    json.dumps(
                        {"temperature": 0},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
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
        created_at=NOW,
    )
    return repo, freeze_path, checksum_path, shas, qrels


def _mesa_response(chunk_id="mesa-chunk-1"):
    matched = {
        "assertion_id": "assertion-1",
        "tenant_id": "tenant-1",
        "dataset_id": "dataset-1",
        "document_id": "document-1",
        "revision_id": "revision-1",
        "chunk_id": chunk_id,
        "status": "ACTIVE",
        "jurisdiction": "TR",
        "valid_from": "",
        "valid_to": "",
    }
    return {
        "session_id": "session-1",
        "dataset_ids": ["dataset-1"],
        "results": [
            {
                "candidate_id": "assertion-1",
                "evidence_id": "assertion-1",
                "assertion_id": "assertion-1",
                "source_chunk_id": chunk_id,
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


def _run_to_scoring(
    tmp_path: Path,
    *,
    answer=True,
    cited_id="mesa-chunk-1",
    answer_model="openai/gpt-oss-20b",
    retrieval_query="Question?",
    context_dataset="dataset-1",
):
    repo, freeze_path, checksum_path, shas, qrels = _authority_freeze(tmp_path)
    run_dir = tmp_path / RUN_ID
    tx = CertificationTransaction(RUN_ID, run_dir)
    tx.execute_bootstrap()
    tx.execute_freeze(
        freeze_path,
        checksum_path,
        repository_root=repo,
        current_repository_shas=shas,
    )

    def raw_builder(path: Path):
        store = RunArtifactStore(path, RUN_ID)
        store.persist_raw_retrieval(
            query_id="Q-1",
            request={
                "session_id": "session-1",
                "dataset_ids": ["dataset-1"],
                "query": retrieval_query,
                "limit": 5,
            },
            response=_mesa_response(),
            transport_status=200,
            timestamp_utc=NOW,
            latency_ms=1,
            runtime_lock_sha256="0" * 64,
        )
        if answer:
            context = normalize_context_response(
                run_id=RUN_ID,
                query_id="Q-1",
                response={
                    "tenant_id": "tenant-1",
                    "agent_id": "agent-1",
                    "session_id": "session-1",
                    "dataset_ids": [context_dataset],
                    "context": "Exact legal fact",
                    "canonical_memories": [
                        {
                            "source_chunk_id": "mesa-chunk-1",
                            "evidence_id": "assertion-1",
                        }
                    ],
                },
                api_version="v4",
                mesa_sha=MESA_SHA,
            )
            execute_answer_and_persist(
                store=store,
                context=context,
                question="Question?",
                system_prompt="Use only evidence",
                answer_instruction="Return structured answer",
                model=answer_model,
                request_parameters={"temperature": 0},
                transport=_Transport(cited_id=cited_id),
                timestamp_utc=NOW,
            )

    tx.execute_raw_execution(raw_builder)
    tx.execute_raw_sealing()
    tx.execute_oracle_audit()
    return tx, qrels


def test_frozen_raw_to_official_scorer_binding(tmp_path: Path) -> None:
    tx, _ = _run_to_scoring(tmp_path)
    report = tx.execute_scoring(
        answer_records=[{"query_id": "FORGED", "status": "PASS"}],
        scoring_fn=lambda _: {"status": "PASS"},
    )
    assert report["status"] == "PASS"
    assert report["item_count"] == 2
    summary = json.loads((tx.run_dir / "scoring-summary.json").read_text())
    assert summary["scorer_version"] == "profile-b-official-v2"
    assert summary["metrics"]["answerable_recall_at_5"] == 1.0
    assert summary["metrics"]["answerable_pass_rate"] == 1.0
    assert all(item["query_id"] == "Q-1" for item in report["items"])


def test_missing_answer_lane_cannot_manufacture_answer_metrics(tmp_path: Path) -> None:
    tx, _ = _run_to_scoring(tmp_path, answer=False)
    report = tx.execute_scoring()
    assert report["status"] == "FAIL"
    answer = report["lane_reports"]["answers"]
    assert answer["population_complete"] is False
    assert answer["metrics"]["answerable_pass_rate"] is None


def test_citation_outside_exact_context_cannot_pass_answer(tmp_path: Path) -> None:
    tx, _ = _run_to_scoring(tmp_path, cited_id="mesa-chunk-2")
    report = tx.execute_scoring()
    answer_item = report["lane_reports"]["answers"]["items"][0]
    assert answer_item["status"] != "PASS"
    assert any(
        "outside retrieved context" in reason for reason in answer_item["reasons"]
    )


def test_qrel_drift_after_freeze_is_rejected(tmp_path: Path) -> None:
    tx, qrels = _run_to_scoring(tmp_path)
    qrels.write_text(qrels.read_text() + "\n", encoding="utf-8")
    with pytest.raises(TransactionError, match="qrels_path.*differs from freeze"):
        tx.execute_scoring()


def test_score_report_hash_binds_official_report(tmp_path: Path) -> None:
    tx, _ = _run_to_scoring(tmp_path)
    tx.execute_scoring()
    summary = json.loads((tx.run_dir / "scoring-summary.json").read_text())
    assert (
        summary["score_artifact_hash"]
        == hashlib.sha256((tx.run_dir / "scoring-report.json").read_bytes()).hexdigest()
    )


def test_answer_provider_identity_must_match_freeze(tmp_path: Path) -> None:
    tx, _ = _run_to_scoring(tmp_path, answer_model="forged-model")
    with pytest.raises(TransactionError, match="identity differs from freeze"):
        tx.execute_scoring()


def test_retrieval_query_must_equal_frozen_gt_question(tmp_path: Path) -> None:
    tx, _ = _run_to_scoring(tmp_path, retrieval_query="oracle-expanded query")
    with pytest.raises(TransactionError, match="frozen GT question"):
        tx.execute_scoring()


def test_answer_context_scope_must_match_retrieval_scope(tmp_path: Path) -> None:
    tx, _ = _run_to_scoring(tmp_path, context_dataset="other-dataset")
    with pytest.raises(TransactionError, match="session or dataset identity mismatch"):
        tx.execute_scoring()


def test_official_transaction_uses_frozen_producers_and_contract_blockers(
    tmp_path: Path,
) -> None:
    tx, _ = _run_to_scoring(tmp_path)
    tx.execute_scoring()
    write_sealed_measurement(
        tx.run_dir / "scope-isolation.json",
        {
            "schema_version": "2.0",
            "run_id": RUN_ID,
            "mesa_contract_capabilities": {
                "candidate_scope_identity": False,
                "pre_rank_exclusion_audit": False,
            },
            "negative_cases": [],
        },
    )
    write_sealed_measurement(
        tx.run_dir / "graph-ablation.json",
        {
            "schema_version": "2.0",
            "run_id": RUN_ID,
            "mesa_contract_capabilities": {
                "stable_path_identity": False,
                "native_graph_on_off_switch": False,
            },
            "pairs": [],
        },
    )

    results = tx.execute_gate_evaluation(
        gate_metrics={gate: {"forged": True} for gate in ("B9", "B10", "B11")},
        gate_evidence={gate: ["forged.json"] for gate in ("B9", "B10", "B11")},
    )

    by_gate = {result.gate_id: result for result in results}
    assert by_gate["B9"].status is GateStatus.BLOCKED
    assert by_gate["B10"].status is GateStatus.BLOCKED
    assert by_gate["B11"].status is GateStatus.BLOCKED
    assert any(result.status is not GateStatus.PASS for result in results)
    observations = json.loads((tx.run_dir / "gate-observations.json").read_text())
    assert observations["producer_code_sha256"]
