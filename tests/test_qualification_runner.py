"""Tests for the authoritative Profile B VM Qualification Runner."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.qualification_runner import (
    QualificationConfig,
    QualificationRunnerError,
    run_profile_b_qualification,
    _validate_official_provider_contract,
)
from harness.official_scoring import load_frozen_scoring_authority
from harness.scope_collector import ScopeTestCase
from tests.scope_fixture_support import frozen_scope_fixture_authority
from tests.test_phase7_scope_collector import _mock_mesa_response
from tests.test_phase8_9_graph_and_state_proof import (
    _mock_graph_executor,
    _setup_mock_stores,
)

ROOT = Path(__file__).resolve().parents[1]
MESA_SHA = "a" * 40
DATA_SHA = "b" * 40
CERT_SHA = "c" * 40


def _setup_test_repo(
    tmp_path: Path, run_id: str = "RUN-QUAL-TEST"
) -> tuple[Path, Path, Path, Path, Path, Path]:
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
    scope_authority, scope_identity_rows = frozen_scope_fixture_authority(
        authorized_document="document-1"
    )
    identity_rows = [
        {
            "mesa_chunk_id": "mesa-chunk-1",
            "source_chunk_id": "source-chunk-1",
            "content_hash": "1" * 64,
            "delivery_state": "COMMITTED",
            "document_id": "document-1",
            "remote_mutation_id": "mutation-1",
            "version_id": "revision-1",
        },
        *scope_identity_rows,
    ]
    identity.write_text(
        "\n".join(json.dumps(row) for row in identity_rows) + "\n",
        encoding="utf-8",
    )
    materials["identity_map"] = [identity]

    normalization = repo / "config" / "scoring-normalization.json"
    normalization.parent.mkdir(parents=True, exist_ok=True)
    normalization.write_text(
        (ROOT / "config" / "scoring-normalization.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    materials["normalization"] = [normalization]

    # Required harness source files
    harness_dir = repo / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    harness_files = []
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
        "qualification_runner.py",
        "finalizer.py",
        "mesa_transport.py",
        "verdict.py",
    ):
        dest = harness_dir / name
        dest.write_text(
            (ROOT / "harness" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
        harness_files.append(dest)
    materials["harness_source"] = harness_files

    scorer_dir = repo / "harness"
    scorer_files = []
    for name in ("retrieval_scorer.py", "answer_scorer.py", "official_scoring.py"):
        dest = scorer_dir / name
        dest.write_text(
            (ROOT / "harness" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
        scorer_files.append(dest)
    materials["scorer_source"] = scorer_files

    gate_config = repo / "config" / "profile-b-gates.json"
    gate_config.parent.mkdir(parents=True, exist_ok=True)
    gate_config.write_text(
        (ROOT / "config" / "profile-b-gates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
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
            "embedding_authority": {
                "provider": "openai_compatible",
                "endpoint": "https://integrate.api.nvidia.com/v1",
                "model": "nvidia/nemotron-3-embed-1b",
                "dimension": 2048,
                "document_input_type": "passage",
                "query_input_type": "query",
            },
            "extraction_authority": {
                "provider": "openai_compatible",
                "model": "openai/gpt-oss-20b",
                "language": "tr",
                "minimum_max_tokens": 4096,
            },
            "answer_authority": {
                "provider": "openai_compatible",
                "model": "openai/gpt-oss-20b",
                "system_prompt_sha256": "0" * 64,
                "answer_instruction_sha256": "0" * 64,
                "request_parameters_sha256": "0" * 64,
                "context_contract_version": "mesa-e2e.context.v2",
                "source_context_contract": "mesa-e2e.sealed-retrieval-context.v1",
            },
            "scoring_authority": {
                "ground_truth_path": gt.relative_to(repo).as_posix(),
                "qrels_path": qrels.relative_to(repo).as_posix(),
                "identity_map_path": identity.relative_to(repo).as_posix(),
                "normalization_path": normalization.relative_to(repo).as_posix(),
                "mesa_api_version": "v4",
            },
            "mesa_transport": {
                "base_url": "http://127.0.0.1:9",
                "api_version": "v4",
                "expected_mesa_sha": MESA_SHA,
                "implementation": "harness.mesa_transport.urllib-json.v1",
                "runtime_profile": "combined",
            },
            "answer_transport": {
                "base_url": "https://provider.invalid/v1",
                "provider": "openai_compatible",
                "implementation": "harness.answer_execution.urllib-openai-compatible.v1",
            },
            "qualification_scope": {
                "tenant_id": "tenant-auth",
                "workspace_id": "workspace-auth",
                "dataset_ids": ["dataset-legal-1"],
                "agent_id": "agent-auth",
                "expected_principal": "principal-user-1",
            },
            "scope_test_authority": scope_authority,
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
        run_dir=tmp_path / "RUN-TEST",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={
            "MESA": MESA_SHA,
            "MESA_Data": DATA_SHA,
            "MESA_E2E_Certification": CERT_SHA,
        },
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
        run_dir=tmp_path / "RUN-TEST",
        freeze_path=tmp_path / "nonexistent-freeze.json",
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={
            "MESA": MESA_SHA,
            "MESA_Data": DATA_SHA,
            "MESA_E2E_Certification": CERT_SHA,
        },
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
    )
    with pytest.raises(QualificationRunnerError, match="freeze_path missing"):
        run_profile_b_qualification(config)


def test_qualification_runner_rejects_unresolved_repository_shas(
    tmp_path: Path,
) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    config = QualificationConfig(
        run_id="RUN-TEST",
        run_dir=tmp_path / "RUN-TEST",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={
            "MESA": "short",
            "MESA_Data": DATA_SHA,
            "MESA_E2E_Certification": CERT_SHA,
        },
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
    )
    with pytest.raises(
        QualificationRunnerError, match="unresolved repository identity"
    ):
        run_profile_b_qualification(config)


def test_qualification_runner_rejects_missing_stores(tmp_path: Path) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    config = QualificationConfig(
        run_id="RUN-TEST",
        run_dir=tmp_path / "RUN-TEST",
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={
            "MESA": MESA_SHA,
            "MESA_Data": DATA_SHA,
            "MESA_E2E_Certification": CERT_SHA,
        },
        sqlite_path=tmp_path / "missing.db",
        lancedb_dir=lance,
        kuzu_dir=kuzu,
    )
    with pytest.raises(QualificationRunnerError, match="SQLite store not found"):
        run_profile_b_qualification(config)


def test_qualification_config_rejects_caller_quiescence_claims(tmp_path: Path) -> None:
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path)
    with pytest.raises(TypeError, match="quiescence_evidence"):
        QualificationConfig(
            run_id="RUN-TEST",
            run_dir=tmp_path / "RUN-TEST",
            freeze_path=fp,
            checksum_path=cp,
            repository_root=repo,
            current_repository_shas={
                "MESA": MESA_SHA,
                "MESA_Data": DATA_SHA,
                "MESA_E2E_Certification": CERT_SHA,
            },
            sqlite_path=sql,
            lancedb_dir=lance,
            kuzu_dir=kuzu,
            quiescence_evidence={"runtime_freeze_verified": True},  # type: ignore[call-arg]
        )


def test_qualification_runner_rejects_arbitrary_executor_callables(
    tmp_path: Path,
) -> None:
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
        current_repository_shas={
            "MESA": MESA_SHA,
            "MESA_Data": DATA_SHA,
            "MESA_E2E_Certification": CERT_SHA,
        },
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
        gate_config_path=repo / "config" / "profile-b-gates.json",
        mesa_base_url="http://127.0.0.1:9",
        mesa_api_key="test-only-key",
    )

    with pytest.raises(TypeError, match="mesa_scope_executor"):
        run_profile_b_qualification(
            config,
            mesa_scope_executor=scope_executor,  # type: ignore[call-arg]
            mesa_graph_executor=_mock_graph_executor,  # type: ignore[call-arg]
            mesa_search_executor=search_executor,  # type: ignore[call-arg]
        )


def test_qualification_runner_missing_rel_authority_fails_before_transport(
    tmp_path: Path,
) -> None:
    run_id = "RUN-MISSING-REL"
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path, run_id=run_id)
    config = QualificationConfig(
        run_id=run_id,
        run_dir=tmp_path / run_id,
        freeze_path=fp,
        checksum_path=cp,
        repository_root=repo,
        current_repository_shas={
            "MESA": MESA_SHA,
            "MESA_Data": DATA_SHA,
            "MESA_E2E_Certification": CERT_SHA,
        },
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
        mesa_base_url="http://127.0.0.1:9",
        mesa_api_key="test-only-key",
    )
    with pytest.raises(
        QualificationRunnerError,
        match="exactly 10 RELATIONAL queries",
    ):
        run_profile_b_qualification(config)


def _reseal_freeze(freeze_path: Path, checksum_path: Path, payload: dict) -> None:
    freeze_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {freeze_path.name}\n", encoding="utf-8")


def _runner_config(
    tmp_path: Path,
    run_id: str,
    repo: Path,
    freeze_path: Path,
    checksum_path: Path,
    sql: Path,
    lance: Path,
    kuzu: Path,
) -> QualificationConfig:
    return QualificationConfig(
        run_id=run_id,
        run_dir=tmp_path / run_id,
        freeze_path=freeze_path,
        checksum_path=checksum_path,
        repository_root=repo,
        current_repository_shas={
            "MESA": MESA_SHA,
            "MESA_Data": DATA_SHA,
            "MESA_E2E_Certification": CERT_SHA,
        },
        sqlite_path=sql,
        lancedb_dir=lance,
        kuzu_dir=kuzu,
        mesa_base_url="http://127.0.0.1:9",
        mesa_api_key="test-only-key",
    )


def test_official_provider_contract_matches_canonical_config(tmp_path: Path) -> None:
    run_id = "RUN-PROVIDER-CONTRACT-PASS"
    repo, fp, _cp, _sql, _lance, _kuzu = _setup_test_repo(
        tmp_path, run_id=run_id
    )
    freeze = json.loads(fp.read_text(encoding="utf-8"))
    authority = load_frozen_scoring_authority(
        freeze_path=fp, repository_root=repo, run_id=run_id
    )

    _validate_official_provider_contract(freeze, authority)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("provider", "wrong-provider"),
        ("model", "wrong-embedding"),
        ("dimension", 1024),
        ("document_input_type", "query"),
        ("query_input_type", "passage"),
        ("endpoint", "https://wrong-provider.invalid/v1"),
    ],
)
def test_official_embedding_contract_drift_fails_closed(
    tmp_path: Path, field: str, bad_value: object
) -> None:
    run_id = f"RUN-EMBED-DRIFT-{field}"
    repo, fp, cp, _sql, _lance, _kuzu = _setup_test_repo(
        tmp_path, run_id=run_id
    )
    freeze = json.loads(fp.read_text(encoding="utf-8"))
    freeze["runtime_identities"]["embedding_authority"][field] = bad_value
    _reseal_freeze(fp, cp, freeze)
    authority = load_frozen_scoring_authority(
        freeze_path=fp, repository_root=repo, run_id=run_id
    )

    with pytest.raises(QualificationRunnerError, match="embedding provider/model"):
        _validate_official_provider_contract(freeze, authority)


def test_official_answer_model_drift_fails_closed(tmp_path: Path) -> None:
    run_id = "RUN-ANSWER-MODEL-DRIFT"
    repo, fp, cp, _sql, _lance, _kuzu = _setup_test_repo(
        tmp_path, run_id=run_id
    )
    freeze = json.loads(fp.read_text(encoding="utf-8"))
    freeze["runtime_identities"]["answer_authority"]["model"] = "wrong-answer-model"
    _reseal_freeze(fp, cp, freeze)
    authority = load_frozen_scoring_authority(
        freeze_path=fp, repository_root=repo, run_id=run_id
    )

    with pytest.raises(QualificationRunnerError, match="answer provider/model"):
        _validate_official_provider_contract(freeze, authority)


def test_official_extraction_contract_drift_fails_closed(tmp_path: Path) -> None:
    run_id = "RUN-EXTRACTION-MODEL-DRIFT"
    repo, fp, cp, _sql, _lance, _kuzu = _setup_test_repo(
        tmp_path, run_id=run_id
    )
    freeze = json.loads(fp.read_text(encoding="utf-8"))
    freeze["runtime_identities"]["extraction_authority"]["model"] = (
        "wrong-extraction-model"
    )
    _reseal_freeze(fp, cp, freeze)
    authority = load_frozen_scoring_authority(
        freeze_path=fp, repository_root=repo, run_id=run_id
    )

    with pytest.raises(QualificationRunnerError, match="extraction provider/model"):
        _validate_official_provider_contract(freeze, authority)


def test_qualification_runner_missing_ground_truth_fails_closed(tmp_path: Path) -> None:
    run_id = "RUN-MISSING-GT"
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path, run_id=run_id)
    (repo / "ground-truth" / "test.jsonl").unlink()
    with pytest.raises(
        QualificationRunnerError, match="Contract freeze verification failed"
    ):
        run_profile_b_qualification(
            _runner_config(tmp_path, run_id, repo, fp, cp, sql, lance, kuzu)
        )


def test_qualification_runner_invalid_qrels_fails_before_transport(
    tmp_path: Path,
) -> None:
    run_id = "RUN-INVALID-QRELS"
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path, run_id=run_id)
    qrels = repo / "ground-truth" / "qrels.jsonl"
    qrels.write_text('{"query_id": 7}\n', encoding="utf-8")
    freeze = json.loads(fp.read_text(encoding="utf-8"))
    rel = qrels.relative_to(repo).as_posix()
    for material in freeze["materials"]:
        if material["path"] == rel:
            material["sha256"] = hashlib.sha256(qrels.read_bytes()).hexdigest()
    _reseal_freeze(fp, cp, freeze)
    with pytest.raises(QualificationRunnerError, match="GT/qrels validation failed"):
        run_profile_b_qualification(
            _runner_config(tmp_path, run_id, repo, fp, cp, sql, lance, kuzu)
        )


def test_qualification_runner_scoring_loader_exception_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "RUN-SCORING-LOAD-FAIL"
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path, run_id=run_id)

    def fail_loader(**_kwargs):
        from harness.official_scoring import ScoringAuthorityUnavailable

        raise ScoringAuthorityUnavailable("injected load failure")

    monkeypatch.setattr(
        "harness.qualification_runner.load_frozen_scoring_authority",
        fail_loader,
    )
    with pytest.raises(
        QualificationRunnerError, match="official frozen scoring authority unavailable"
    ):
        run_profile_b_qualification(
            _runner_config(tmp_path, run_id, repo, fp, cp, sql, lance, kuzu)
        )


def test_qualification_runner_rejects_answer_executor_injection(tmp_path: Path) -> None:
    run_id = "RUN-ANSWER-INJECTION"
    repo, fp, cp, sql, lance, kuzu = _setup_test_repo(tmp_path, run_id=run_id)
    with pytest.raises(TypeError, match="answer_executor"):
        run_profile_b_qualification(
            _runner_config(tmp_path, run_id, repo, fp, cp, sql, lance, kuzu),
            answer_executor=lambda *_args: {},  # type: ignore[call-arg]
        )
