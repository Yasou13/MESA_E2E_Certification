"""Deterministic provider contract tests for Profile B (Ollama Magibu/Qwen).

Validates frozen provider selection vs observed runtime identity offline without
network dependencies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from harness.answer_execution import (
    OpenAICompatibleHTTPTransport,
    ProviderRetryPolicy,
)
from harness.gates import (
    GateConfig,
    evaluate_threshold_gate,
    load_gate_config,
)
from harness.metric_producers import (
    PRODUCTION_METRIC_PRODUCERS,
    ProducerContext,
    ProducerIntegrityError,
)
from harness.models import ExecutionStatus, GateStatus
from harness.qualification_runner import (
    QualificationConfig,
    QualificationRunnerError,
    _validate_official_provider_contract,
    _trusted_answer_transport,
)
from harness.official_scoring import FrozenScoringAuthority

REPOSITORY = Path(__file__).resolve().parents[1]
GATE_CONFIG_PATH = REPOSITORY / "config" / "profile-b-gates.json"


def _sample_authority(
    *,
    answer_provider: str = "Ollama",
    answer_model: str = "qwen3.5:9b-q4_K_M",
    embedding_provider: str = "Ollama",
    embedding_model: str = "alibayram/embeddingmagibu-200m:latest",
    embedding_dimension: int = 768,
    embedding_digest: str | None = "sha256:magibu-digest-123",
    embedding_normalization: str | None = "l2",
    extraction_provider: str = "Ollama",
    extraction_model: str = "qwen3.5:9b-q4_K_M",
    extraction_language: str = "tr",
    extraction_min_tokens: int = 4096,
    extraction_quantization: str | None = "Q4_K_M",
    answer_digest: str | None = "sha256:qwen-digest-456",
    answer_quantization: str | None = "Q4_K_M",
) -> tuple[FrozenScoringAuthority, dict[str, Any]]:
    official_provider_contract = {
        "embedding": {
            "provider": embedding_provider,
            "model": embedding_model,
            "dimension": embedding_dimension,
            "resolved_digest": embedding_digest,
            "normalization": embedding_normalization,
        },
        "extraction": {
            "provider": extraction_provider,
            "model": extraction_model,
            "language": extraction_language,
            "minimum_max_tokens": extraction_min_tokens,
            "quantization": extraction_quantization,
        },
        "answer": {
            "provider": answer_provider,
            "model": answer_model,
            "resolved_digest": answer_digest,
            "quantization": answer_quantization,
        },
    }
    authority = FrozenScoringAuthority(
        run_id="RUN-PROV-01",
        mesa_sha="a" * 40,
        mesa_api_version="v4",
        ground_truth_path=REPOSITORY / "ground-truth" / "test.jsonl",
        ground_truth_sha256="0" * 64,
        qrels_path=REPOSITORY / "ground-truth" / "qrels.txt",
        qrels_sha256="0" * 64,
        identity_map_path=REPOSITORY / "ground-truth" / "identity_map.jsonl",
        identity_map_sha256="0" * 64,
        normalization_path=REPOSITORY / "config" / "scoring-normalization.json",
        normalization_sha256="0" * 64,
        scorer_sha256="0" * 64,
        scorer_paths=(),
        answer_provider=answer_provider,
        answer_model=answer_model,
        system_prompt_sha256="0" * 64,
        answer_instruction_sha256="0" * 64,
        request_parameters_sha256="0" * 64,
        context_contract_version="mesa-e2e.context.v2",
        source_context_contract="mesa-e2e.sealed-retrieval-context.v1",
        retrieval_top_k=5,
        answer_context_policy="sealed_retrieval_top_k",
        official_provider_contract=official_provider_contract,
        profile_contract_sha256="0" * 64,
    )
    freeze = {
        "run_id": "RUN-PROV-01",
        "runtime_identities": {
            "embedding_authority": {
                "provider": embedding_provider,
                "endpoint": "http://127.0.0.1:11434",
                "model": embedding_model,
                "dimension": embedding_dimension,
                "resolved_digest": embedding_digest,
                "normalization": embedding_normalization,
            },
            "extraction_authority": {
                "provider": extraction_provider,
                "endpoint": "http://127.0.0.1:11434",
                "model": extraction_model,
                "language": extraction_language,
                "minimum_max_tokens": extraction_min_tokens,
                "quantization": extraction_quantization,
            },
            "answer_authority": {
                "provider": answer_provider,
                "model": answer_model,
                "resolved_digest": answer_digest,
                "quantization": answer_quantization,
            },
        },
    }
    return authority, freeze


# =========================================================================
# SECTION 11: EMBEDDING CONTRACT TESTS (A through F)
# =========================================================================

def test_embedding_contract_a_ollama_magibu_768_correct_digest_passes() -> None:
    authority, freeze = _sample_authority(
        embedding_provider="Ollama",
        embedding_model="alibayram/embeddingmagibu-200m:latest",
        embedding_dimension=768,
        embedding_digest="sha256:magibu-digest-123",
    )
    # Must pass without error
    _validate_official_provider_contract(freeze, authority)


def test_embedding_contract_b_correct_model_wrong_dimension_fails() -> None:
    authority, freeze = _sample_authority(
        embedding_provider="Ollama",
        embedding_model="alibayram/embeddingmagibu-200m:latest",
        embedding_dimension=768,
    )
    # Runtime observed dimension is 2048 instead of 768
    freeze["runtime_identities"]["embedding_authority"]["dimension"] = 2048
    with pytest.raises(QualificationRunnerError, match="dimension"):
        _validate_official_provider_contract(freeze, authority)


def test_embedding_contract_c_nemotron_2048_under_magibu_contract_fails() -> None:
    authority, freeze = _sample_authority(
        embedding_provider="Ollama",
        embedding_model="alibayram/embeddingmagibu-200m:latest",
        embedding_dimension=768,
    )
    # Runtime observed Nemotron 2048
    freeze["runtime_identities"]["embedding_authority"]["provider"] = "openai_compatible"
    freeze["runtime_identities"]["embedding_authority"]["model"] = "nvidia/nemotron-3-embed-1b"
    freeze["runtime_identities"]["embedding_authority"]["dimension"] = 2048
    with pytest.raises(QualificationRunnerError, match="provider|model"):
        _validate_official_provider_contract(freeze, authority)


def test_embedding_contract_d_correct_tag_wrong_digest_fails() -> None:
    authority, freeze = _sample_authority(
        embedding_provider="Ollama",
        embedding_model="alibayram/embeddingmagibu-200m:latest",
        embedding_dimension=768,
        embedding_digest="sha256:magibu-digest-expected",
    )
    # Runtime resolved a different digest under the mutable tag
    freeze["runtime_identities"]["embedding_authority"]["resolved_digest"] = "sha256:magibu-digest-mutated"
    with pytest.raises(QualificationRunnerError, match="digest"):
        _validate_official_provider_contract(freeze, authority)


def test_embedding_contract_e_missing_model_identity_fails() -> None:
    authority, freeze = _sample_authority()
    freeze["runtime_identities"]["embedding_authority"]["model"] = ""
    with pytest.raises(QualificationRunnerError, match="model"):
        _validate_official_provider_contract(freeze, authority)


def test_embedding_contract_f_missing_mandatory_dimension_fails() -> None:
    authority, freeze = _sample_authority()
    freeze["runtime_identities"]["embedding_authority"]["dimension"] = None
    with pytest.raises(QualificationRunnerError, match="dimension"):
        _validate_official_provider_contract(freeze, authority)


# =========================================================================
# SECTION 12: ANSWER MODEL CONTRACT TESTS
# =========================================================================

def test_answer_contract_correct_ollama_qwen_passes() -> None:
    authority, freeze = _sample_authority(
        answer_provider="Ollama",
        answer_model="qwen3.5:9b-q4_K_M",
        answer_digest="sha256:qwen-digest-456",
        answer_quantization="Q4_K_M",
    )
    _validate_official_provider_contract(freeze, authority)


def test_answer_contract_gpt_oss_under_qwen_contract_fails() -> None:
    authority, freeze = _sample_authority(
        answer_provider="Ollama",
        answer_model="qwen3.5:9b-q4_K_M",
    )
    # Try to use legacy GPT-OSS
    authority_with_gpt = replace(authority, answer_model="openai/gpt-oss-20b")
    with pytest.raises(QualificationRunnerError, match="answer provider/model differs"):
        _validate_official_provider_contract(freeze, authority_with_gpt)


def test_answer_contract_different_qwen_model_fails() -> None:
    authority, freeze = _sample_authority(
        answer_provider="Ollama",
        answer_model="qwen3.5:9b-q4_K_M",
    )
    authority_with_diff = replace(authority, answer_model="qwen2.5:72b")
    with pytest.raises(QualificationRunnerError, match="answer provider/model differs"):
        _validate_official_provider_contract(freeze, authority_with_diff)


def test_answer_contract_same_tag_wrong_digest_fails() -> None:
    authority, freeze = _sample_authority(
        answer_provider="Ollama",
        answer_model="qwen3.5:9b-q4_K_M",
        answer_digest="sha256:expected-digest-111",
    )
    freeze["runtime_identities"]["answer_authority"]["resolved_digest"] = "sha256:wrong-digest-222"
    with pytest.raises(QualificationRunnerError, match="digest"):
        _validate_official_provider_contract(freeze, authority)


def test_answer_contract_missing_provider_identity_fails() -> None:
    authority, freeze = _sample_authority()
    freeze["runtime_identities"]["answer_authority"]["provider"] = ""
    authority_empty = replace(authority, answer_provider="")
    with pytest.raises(QualificationRunnerError, match="answer provider/model differs"):
        _validate_official_provider_contract(freeze, authority_empty)


# =========================================================================
# SECTION 13: MUTABLE TAG SAFETY
# =========================================================================

def test_mutable_tag_safety_digest_mismatch_fails() -> None:
    authority, freeze = _sample_authority(
        embedding_model="alibayram/embeddingmagibu-200m:latest",
        embedding_digest="sha256:original-frozen-digest",
    )
    # Tag is unchanged ("alibayram/embeddingmagibu-200m:latest"), but digest changed
    freeze["runtime_identities"]["embedding_authority"]["resolved_digest"] = "sha256:new-pushed-digest"
    with pytest.raises(QualificationRunnerError, match="digest"):
        _validate_official_provider_contract(freeze, authority)


# =========================================================================
# TRANSPORT: HTTP & CONFIGURABLE PROVIDER & OPTIONAL API KEY
# =========================================================================

def test_answer_transport_supports_http_and_ollama_provider() -> None:
    transport = OpenAICompatibleHTTPTransport(
        base_url="http://10.70.157.9:11434/v1",
        api_key="",
        timeout_seconds=30.0,
        provider="Ollama",
    )
    assert transport.base_url == "http://10.70.157.9:11434/v1"
    assert transport.provider_name == "Ollama"
    assert transport.identity_sha256 is not None
