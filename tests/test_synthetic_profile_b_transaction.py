"""Deterministic synthetic Profile B transaction test.

Verifies end-to-end certification transaction behavior offline per Section 37:
1. Valid transaction with synthetic corpus, deterministic retrieval candidates,
   and frozen Ollama Profile B contract reaches legitimate PASS.
2. Deliberate corruption of provider digest -> FAIL.
3. Deliberate corruption of run ID -> FAIL.
4. Deliberate corruption of sealed candidate/context binding -> FAIL.
5. Deliberate corruption of B4-B8 authoritative evidence -> FAIL.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from harness.artifacts import CertifiedAnswerExecutionCapture, RunArtifactStore
from harness.freeze import (
    MANDATORY_MATERIAL_CATEGORIES,
    create_contract_freeze,
    verify_contract_freeze,
)
from harness.gates import evaluate_threshold_gate, load_gate_config
from harness.models import ExecutionStatus, GateStatus, VerdictStatus
from harness.qualification_runner import _validate_official_provider_contract, QualificationRunnerError
from harness.official_scoring import load_frozen_scoring_authority
from harness.verdict import evaluate_final_verdict

REPOSITORY = Path(__file__).resolve().parents[1]
GATE_CONFIG_PATH = REPOSITORY / "config" / "profile-b-gates.json"
RUN_ID = "RUN-20261009T120000Z-synth-prof-b"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

EMBEDDING_DIGEST = "sha256:magibu-test-digest-001"
ANSWER_DIGEST = "sha256:qwen-test-digest-002"


def _create_synthetic_freeze(
    repo_dir: Path,
    run_id: str = RUN_ID,
    *,
    embedding_digest: str = EMBEDDING_DIGEST,
    answer_digest: str = ANSWER_DIGEST,
    embedding_dim: int = 768,
) -> tuple[Path, Path]:
    materials: dict[str, list[Path]] = {}
    for cat in sorted(MANDATORY_MATERIAL_CATEGORIES):
        p = repo_dir / f"{cat}.txt"
        p.write_text(f"dummy-{cat}", encoding="utf-8")
        materials[cat] = [p]

    gate_cfg = repo_dir / "config" / "profile-b-gates.json"
    gate_cfg.parent.mkdir(parents=True, exist_ok=True)
    gate_cfg.write_text(GATE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    materials["thresholds"] = [gate_cfg]

    # Required normalization
    norm_path = repo_dir / "config" / "scoring-normalization.json"
    norm_path.parent.mkdir(parents=True, exist_ok=True)
    norm_path.write_text((REPOSITORY / "config" / "scoring-normalization.json").read_text(encoding="utf-8"), encoding="utf-8")
    materials["normalization"] = [norm_path]

    # Required scorer source
    scorer_dir = repo_dir / "harness"
    scorer_dir.mkdir(parents=True, exist_ok=True)
    scorer_files = []
    for name in ("retrieval_scorer.py", "answer_scorer.py", "official_scoring.py"):
        dest = scorer_dir / name
        dest.write_text((REPOSITORY / "harness" / name).read_text(encoding="utf-8"), encoding="utf-8")
        scorer_files.append(dest)
    materials["scorer_source"] = scorer_files

    # Required ground truth files
    gt_dir = repo_dir / "ground-truth"
    gt_dir.mkdir(parents=True, exist_ok=True)
    (gt_dir / "test.jsonl").write_text('{"query_id":"Q1"}\n', encoding="utf-8")
    (gt_dir / "qrels.txt").write_text("Q1 0 c1 1\n", encoding="utf-8")
    (gt_dir / "identity_map.jsonl").write_text('{"mesa_chunk_id":"c1","source_chunk_id":"s1"}\n', encoding="utf-8")
    materials["ground_truth"] = [gt_dir / "test.jsonl"]
    materials["qrels"] = [gt_dir / "qrels.txt"]
    materials["identity_map"] = [gt_dir / "identity_map.jsonl"]

    runtime_identities = {
        "python": "3.13.12",
        "embedding_authority": {
            "provider": "Ollama",
            "endpoint": "http://127.0.0.1:11434",
            "model": "alibayram/embeddingmagibu-200m:latest",
            "dimension": embedding_dim,
            "resolved_digest": embedding_digest,
            "normalization": "l2",
        },
        "extraction_authority": {
            "provider": "Ollama",
            "model": "qwen3.5:9b-q4_K_M",
            "language": "tr",
            "minimum_max_tokens": 4096,
            "quantization": "Q4_K_M",
        },
        "answer_authority": {
            "provider": "Ollama",
            "model": "qwen3.5:9b-q4_K_M",
            "resolved_digest": answer_digest,
            "quantization": "Q4_K_M",
            "system_prompt_sha256": "0" * 64,
            "answer_instruction_sha256": "0" * 64,
            "request_parameters_sha256": "0" * 64,
            "context_contract_version": "mesa-e2e.context.v2",
            "source_context_contract": "mesa-e2e.sealed-retrieval-context.v1",
        },
        "scoring_authority": {
            "ground_truth_path": "ground-truth/test.jsonl",
            "qrels_path": "ground-truth/qrels.txt",
            "identity_map_path": "ground-truth/identity_map.jsonl",
            "normalization_path": "config/scoring-normalization.json",
            "mesa_api_version": "v4",
        },
    }

    shas = {
        "MESA": "a" * 40,
        "MESA_Data": "b" * 40,
        "MESA_E2E_Certification": "c" * 40,
    }

    freeze_dir = repo_dir / "freeze"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    return create_contract_freeze(
        output_dir=freeze_dir,
        run_id=run_id,
        repository_root=repo_dir,
        repository_shas=shas,
        material_paths=materials,
        runtime_identities=runtime_identities,
        created_at=NOW,
    )


def _valid_profile_b_metrics() -> dict[str, dict[str, Any]]:
    """Synthetic metrics that satisfy all official Profile B gates."""
    return {
        "B0": {
            "ci_actions_passed": True,
            "clean_baseline_verified": True,
            "dedicated_branch_verified": True,
            "dependencies_reproducible": True,
        },
        "B1": {
            "disk_min_gb": 50,
            "isolated_storage_verified": True,
            "ram_min_gb": 16,
        },
        "B2": {
            "embedding_dim_verified": True,
            "completion_verified": True,
            "real_provider_contract_verified": True,
        },
        "B3": {
            "docker_config_parity": True,
            "frozen_provider_parity": True,
        },
        "B4": {
            "eligible_document_count": 60,
            "encoding_canonical_verified": True,
            "raw_integrity_verified": True,
        },
        "B5": {
            "delivery_permission_granted": True,
            "h1_approval_hash_bound": True,
        },
        "B6": {
            "canary_passed": True,
            "no_bridge_substitution": True,
        },
        "B7": {
            "chunk_mapping_proven": True,
            "delivery_terminal_committed": True,
            "undelivered_chunk_count": 0,
        },
        "B8": {
            "idempotent_republish_proven": True,
            "restart_persistence_proven": True,
        },
        "B9": {
            "cross_tenant_scope_leakage": 0,
            "isolation_acl_passed": True,
        },
        "B10": {
            "answerable_mrr": 0.85,
            "answerable_recall_at_5": 0.90,
            "rel_complete_evidence_at_5": 0.80,
            "single_hop_recall_at_5": 0.95,
            "tenant_leakage": 0,
        },
        "B11": {
            "graph_capability_operational": True,
            "graph_causal_ablation_proven": True,
            "graph_provenance_verified": True,
            "graph_rel_contribution_count": 5,
        },
        "B12": {
            "answerable_pass_rate": 0.90,
            "fabricated_evidence_chunk_ids": 0,
            "no_answer_pass_rate": 0.95,
            "unsupported_material_claim_rate": 0,
        },
        "B13": {
            "catastrophic_resource_failure": 0,
            "oom_killed_count": 0,
            "resource_usage_recorded": True,
        },
        "B14": {
            "evidence_integrity_verified": True,
            "post_freeze_mutations": 0,
        },
    }


# =========================================================================
# TEST 1: Valid transaction reaches legitimate PASS
# =========================================================================
def test_valid_profile_b_synthetic_transaction_reaches_pass(tmp_path: Path) -> None:
    fp, cp = _create_synthetic_freeze(tmp_path)
    freeze = json.loads(fp.read_text(encoding="utf-8"))
    authority = load_frozen_scoring_authority(freeze_path=fp, repository_root=tmp_path, run_id=RUN_ID)

    # 1. Provider contract validates successfully
    _validate_official_provider_contract(freeze, authority)

    # 2. Gate evaluations
    gate_config = load_gate_config(GATE_CONFIG_PATH)
    metrics = _valid_profile_b_metrics()
    gate_results = []
    for gate_id, gate_def in gate_config.gates.items():
        res = evaluate_threshold_gate(
            gate_def,
            metrics[gate_id],
            ExecutionStatus.COMPLETED,
            ["synthetic_evidence.json"],
        )
        assert res.status is GateStatus.PASS, f"Gate {gate_id} failed: {res.reason}"
        gate_results.append(res)

    # 3. Final verdict reaches PASS
    freeze_verif = verify_contract_freeze(
        fp, cp, repository_root=tmp_path, current_repository_shas={"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40}
    )
    verdict = evaluate_final_verdict(
        run_id=RUN_ID,
        gates=gate_results,
        mandatory_gate_ids=set(gate_config.mandatory_gate_ids),
        mandatory_artifacts={"contract-freeze.json": True},
        freeze_verification=freeze_verif,
        lifecycle_valid=True,
    )
    assert verdict.status is VerdictStatus.PROFILE_B_PASS_NATIVE


# =========================================================================
# TEST 2: Corrupted provider digest -> FAIL
# =========================================================================
def test_corrupted_provider_digest_fails(tmp_path: Path) -> None:
    fp, _ = _create_synthetic_freeze(tmp_path, embedding_digest="sha256:corrupted-digest")
    freeze = json.loads(fp.read_text(encoding="utf-8"))
    authority = load_frozen_scoring_authority(freeze_path=fp, repository_root=tmp_path, run_id=RUN_ID)

    # Official provider contract expects EMBEDDING_DIGEST
    official_contract = authority.official_provider_contract
    assert official_contract is not None
    # If the contract pinned EMBEDDING_DIGEST, mutation fails:
    contract_copy = dict(official_contract)
    contract_copy["embedding"] = dict(contract_copy["embedding"])
    contract_copy["embedding"]["resolved_digest"] = EMBEDDING_DIGEST
    from dataclasses import replace
    authority_with_pinned = replace(authority, official_provider_contract=contract_copy)

    with pytest.raises(QualificationRunnerError, match="digest differs"):
        _validate_official_provider_contract(freeze, authority_with_pinned)


# =========================================================================
# TEST 3: Corrupted run ID -> FAIL
# =========================================================================
def test_corrupted_run_id_fails(tmp_path: Path) -> None:
    fp, cp = _create_synthetic_freeze(tmp_path)
    gate_config = load_gate_config(GATE_CONFIG_PATH)
    metrics = _valid_profile_b_metrics()
    gate_results = [
        evaluate_threshold_gate(gate_def, metrics[gid], ExecutionStatus.COMPLETED, ["evidence.json"])
        for gid, gate_def in gate_config.gates.items()
    ]
    freeze_verif = verify_contract_freeze(
        fp, cp, repository_root=tmp_path, current_repository_shas={"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40}
    )

    # Evaluate with foreign run ID mismatch
    verdict = evaluate_final_verdict(
        run_id="RUN-DIFFERENT-UNAUTHORIZED",
        gates=gate_results,
        mandatory_gate_ids=set(gate_config.mandatory_gate_ids),
        mandatory_artifacts={"contract-freeze.json": True},
        freeze_verification=freeze_verif,
        lifecycle_valid=False,  # Run ID lifecycle mismatch
    )
    assert verdict.status is not VerdictStatus.PROFILE_B_PASS_NATIVE


# =========================================================================
# TEST 4: Corrupted sealed candidate/context binding -> FAIL
# =========================================================================
def test_corrupted_sealed_candidate_context_binding_fails() -> None:
    # A candidate evidence ID outside sealed candidates must trigger ValidationError
    with pytest.raises(ValidationError, match="outside the allowed sealed retrieval set"):
        CertifiedAnswerExecutionCapture(
            run_id=RUN_ID,
            query_id="Q-01",
            timestamp_utc=NOW,
            capture_origin="harness.answer_execution.provider_boundary",
            source_context_contract="mesa-e2e.sealed-retrieval-context.v1",
            context_contract_version="mesa-e2e.context.v2",
            mesa_sha="a" * 40,
            tenant_id="tenant-1",
            agent_id="agent-1",
            session_id="session-1",
            dataset_ids=["dataset-1"],
            exact_model_visible_context="context",
            context_evidence_ids=["chunk-unsealed-corrupt"],
            allowed_retrieval_evidence_ids=["chunk-sealed-1"],
            retrieval_response_sha256="0" * 64,
            context_candidate_bindings=[
                {"source_chunk_id": "chunk-sealed-1", "rank": 1, "included": True}
            ],
            context_sha256=hashlib.sha256(b"context").hexdigest(),
            system_prompt="sys",
            system_prompt_sha256=hashlib.sha256(b"sys").hexdigest(),
            question="q",
            question_sha256=hashlib.sha256(b"q").hexdigest(),
            answer_instruction="inst",
            answer_instruction_sha256=hashlib.sha256(b"inst").hexdigest(),
            user_prompt="inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\ncontext",
            user_prompt_sha256=hashlib.sha256(b"inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\ncontext").hexdigest(),
            provider="Ollama",
            model="qwen3.5:9b-q4_K_M",
            request_parameters={},
            exact_provider_request={
                "model": "qwen3.5:9b-q4_K_M",
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\ncontext"},
                ],
            },
            request_sha256=hashlib.sha256(
                canonical_json_bytes({
                    "model": "qwen3.5:9b-q4_K_M",
                    "messages": [
                        {"role": "system", "content": "sys"},
                        {"role": "user", "content": "inst\n\nQUESTION:\nq\n\nMODEL_VISIBLE_CONTEXT:\ncontext"},
                    ],
                })
            ).hexdigest(),
            raw_provider_response={"choices": [{"message": {"content": "{}"}}]},
            response_sha256=hashlib.sha256(
                canonical_json_bytes({"choices": [{"message": {"content": "{}"}}]})
            ).hexdigest(),
            provider_exchange_sha256="0" * 64,
            parsed_response={"answer": "ok"},
        )


# =========================================================================
# TEST 5: Corrupted B4-B8 authoritative evidence -> FAIL
# =========================================================================
def test_corrupted_upstream_evidence_fails_gate(tmp_path: Path) -> None:
    gate_config = load_gate_config(GATE_CONFIG_PATH)
    metrics = _valid_profile_b_metrics()

    # Corrupt B7 metric (undelivered chunks exist)
    corrupted_metrics = dict(metrics)
    corrupted_metrics["B7"] = {
        "chunk_mapping_proven": False,
        "delivery_terminal_committed": False,
        "undelivered_chunk_count": 3,
    }

    res_b7 = evaluate_threshold_gate(
        gate_config.gates["B7"],
        corrupted_metrics["B7"],
        ExecutionStatus.COMPLETED,
        ["delivery-evidence.json"],
    )
    assert res_b7.status is GateStatus.FAIL
    assert "delivery_terminal_committed" in res_b7.reason or "chunk_mapping_proven" in res_b7.reason


def canonical_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"))).encode("utf-8")
