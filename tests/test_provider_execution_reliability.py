"""Focused and adversarial tests for provider execution reliability, bounded retries, and attempt provenance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pytest

from harness.answer_execution import (
    AnswerExecutionError,
    OpenAICompatibleHTTPTransport,
    ProviderEmptyCompletionError,
    ProviderEmptyContentError,
    ProviderIncompleteCompletionError,
    ProviderMalformedResponseError,
    ProviderNonStringContentError,
    ProviderRateLimitError,
    ProviderReliabilityTelemetry,
    ProviderRequestError,
    ProviderRetryPolicy,
    ProviderSchemaValidationError,
    ProviderTemporaryServerError,
    ProviderTransportConnectionError,
    ProviderTransportError,
    ProviderTransportExhaustionError,
    ProviderTransportTimeoutError,
    _parse_openai_compatible_response,
    classify_provider_response,
    execute_answer_and_persist,
    parse_retry_after,
)
from harness.artifacts import (
    CertifiedAnswerExecutionCapture,
    RunArtifactStore,
    _sha256_bytes,
    canonical_json_bytes,
)
from harness.execution_provenance import _begin_official_execution
from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.mesa_adapters import NormalizedContextCapture, normalize_context_response
from harness.mesa_transport import MESATransportConfig, TrustedMESATransport
from harness.models import AnswerResponse
from harness.official_scoring import FrozenScoringAuthority
from harness.qualification_runner import (
    QualificationConfig,
    QualificationRunnerError,
    _trusted_answer_transport,
    _validate_static_preconditions,
)
from harness.transaction import CertificationTransaction, TransactionPhase

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[1]


def _make_context(
    run_id: str = "RUN-REL-01",
    query_id: str = "Q01",
    context_text: str = "Evidence document context text.",
) -> NormalizedContextCapture:
    return normalize_context_response(
        run_id=run_id,
        query_id=query_id,
        response={
            "tenant_id": "tenant-alpha",
            "agent_id": "agent-alpha",
            "session_id": "sess-alpha-01",
            "dataset_ids": ["dataset-1"],
            "context": context_text,
            "canonical_memories": [
                {"source_chunk_id": "chunk-001", "evidence_id": "assertion-001"}
            ],
            "estimated_token_count": 10,
            "mutations": [],
        },
        api_version="v4",
        mesa_sha="a" * 40,
    )


def _valid_answer_payload(text: str = "Exact legal conclusion.") -> dict[str, Any]:
    content = json.dumps(
        {
            "answer": text,
            "evidence_chunk_ids": ["chunk-001"],
            "insufficient_evidence": False,
            "claims": [
                {
                    "fact_ids": ["F1"],
                    "text": text,
                    "evidence_chunk_ids": ["chunk-001"],
                }
            ],
        }
    )
    return {
        "id": "chatcmpl-test-01",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
        },
    }


# =========================================================================
# 1. RESPONSE CLASSIFICATION AND STRICT PARSER TESTS (Section 39)
# =========================================================================

def test_response_parser_valid_content():
    payload = _valid_answer_payload()
    parsed = _parse_openai_compatible_response(payload)
    assert parsed.answer == "Exact legal conclusion."
    assert parsed.evidence_chunk_ids == ["chunk-001"]


def test_response_parser_content_none_with_length_raises_incomplete_error():
    payload = {
        "id": "chatcmpl-incomplete",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning": "Extensive reasoning text that hit 4096 tokens limit...",
                },
                "finish_reason": "length",
            }
        ],
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 4096,
            "total_tokens": 4296,
            "completion_tokens_details": {"reasoning_tokens": 4096},
        },
    }
    with pytest.raises(ProviderIncompleteCompletionError) as exc_info:
        _parse_openai_compatible_response(payload)

    err = exc_info.value
    assert err.category == "INCOMPLETE_COMPLETION_TOKEN_LIMIT"
    assert err.finish_reason == "length"
    assert err.completion_tokens == 4096
    assert err.reasoning_tokens == 4096
    # Invariant: reasoning text must never be part of exception message or attributes
    assert "Extensive reasoning" not in str(err)
    assert not hasattr(err, "reasoning")


def test_response_parser_content_none_with_stop_raises_empty_completion():
    payload = {
        "choices": [
            {
                "message": {"role": "assistant", "content": None},
                "finish_reason": "stop",
            }
        ]
    }
    with pytest.raises(ProviderEmptyCompletionError) as exc_info:
        _parse_openai_compatible_response(payload)
    assert exc_info.value.category == "EMPTY_COMPLETION"


def test_response_parser_content_none_without_finish_reason():
    payload = {
        "choices": [
            {"message": {"role": "assistant", "content": None}}
        ]
    }
    with pytest.raises(ProviderMalformedResponseError) as exc_info:
        _parse_openai_compatible_response(payload)
    assert exc_info.value.category == "MALFORMED_RESPONSE"


def test_response_parser_empty_string_content():
    payload = {
        "choices": [
            {
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "stop",
            }
        ]
    }
    with pytest.raises(ProviderEmptyContentError) as exc_info:
        _parse_openai_compatible_response(payload)
    assert exc_info.value.category == "EMPTY_CONTENT"


def test_response_parser_non_string_content():
    payload = {
        "choices": [
            {
                "message": {"role": "assistant", "content": 12345},
                "finish_reason": "stop",
            }
        ]
    }
    with pytest.raises(ProviderNonStringContentError) as exc_info:
        _parse_openai_compatible_response(payload)
    assert exc_info.value.category == "NON_STRING_CONTENT"


def test_response_parser_missing_choices():
    with pytest.raises(ProviderMalformedResponseError, match="choices"):
        _parse_openai_compatible_response({"id": "no-choices"})


def test_response_parser_missing_message():
    with pytest.raises(ProviderMalformedResponseError, match="message"):
        _parse_openai_compatible_response({"choices": [{}]})


def test_response_parser_valid_content_with_missing_finish_reason():
    content = json.dumps(
        {
            "answer": "Valid text without explicit finish reason.",
            "evidence_chunk_ids": ["c1"],
            "insufficient_evidence": False,
            "claims": [],
        }
    )
    payload = {
        "choices": [
            {"message": {"role": "assistant", "content": content}}
        ]
    }
    parsed = _parse_openai_compatible_response(payload)
    assert parsed.answer == "Valid text without explicit finish reason."


def test_response_parser_schema_violation():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"invalid_json": true, "missing_required_fields": true}',
                },
                "finish_reason": "stop",
            }
        ]
    }
    with pytest.raises(ProviderSchemaValidationError) as exc_info:
        _parse_openai_compatible_response(payload)
    assert exc_info.value.category == "ANSWER_SCHEMA_VALIDATION_ERROR"


# =========================================================================
# 2. RETRY POLICY CONFIGURATION AND FREEZE DRIFT (Sections 6, 7, 43)
# =========================================================================

def test_retry_policy_defaults_and_validation():
    policy = ProviderRetryPolicy()
    assert policy.timeout_seconds == 60.0
    assert policy.transport_max_attempts == 2
    assert policy.incomplete_completion_max_attempts == 2
    assert policy.retry_backoff_seconds == 1.0

    with pytest.raises(ValueError, match="timeout_seconds"):
        ProviderRetryPolicy(timeout_seconds=-1)
    with pytest.raises(ValueError, match="transport_max_attempts"):
        ProviderRetryPolicy(transport_max_attempts=0)
    with pytest.raises(ValueError, match="incomplete_completion_max_attempts"):
        ProviderRetryPolicy(incomplete_completion_max_attempts=0)
    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        ProviderRetryPolicy(retry_backoff_seconds=-0.5)


def test_qualification_config_retry_fields_and_preconditions(tmp_path: Path):
    cfg = QualificationConfig(
        run_id="RUN-CFG-01",
        run_dir=tmp_path / "RUN-CFG-01",
        freeze_path=tmp_path / "freeze.json",
        checksum_path=tmp_path / "freeze.SHA256",
        repository_root=REPO,
        current_repository_shas={"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40},
        sqlite_path=tmp_path / "db.sqlite",
        lancedb_dir=tmp_path / "lance",
        kuzu_dir=tmp_path / "kuzu",
        answer_provider_timeout_seconds=180.0,
        answer_provider_transport_max_attempts=3,
        answer_provider_incomplete_completion_max_attempts=2,
        answer_provider_retry_backoff_seconds=0.5,
    )
    policy = cfg.get_answer_retry_policy()
    assert policy.timeout_seconds == 180.0
    assert policy.transport_max_attempts == 3
    assert policy.incomplete_completion_max_attempts == 2
    assert policy.retry_backoff_seconds == 0.5


def test_freeze_drift_rejects_differing_retry_policy(tmp_path: Path):
    run_id = "RUN-DRIFT-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)

    authority = FrozenScoringAuthority(
        run_id=run_id,
        mesa_sha="a" * 40,
        mesa_api_version="v4",
        ground_truth_path=tmp_path / "gt.json",
        ground_truth_sha256="0" * 64,
        qrels_path=tmp_path / "qrels.json",
        qrels_sha256="0" * 64,
        identity_map_path=tmp_path / "id.json",
        identity_map_sha256="0" * 64,
        normalization_path=tmp_path / "norm.json",
        normalization_sha256="0" * 64,
        scorer_sha256="0" * 64,
        scorer_paths=(),
        answer_provider="openai_compatible",
        answer_model="openai/gpt-oss-20b",
        system_prompt_sha256=hashlib.sha256(b"sys").hexdigest(),
        answer_instruction_sha256=hashlib.sha256(b"inst").hexdigest(),
        request_parameters_sha256=hashlib.sha256(b"{}").hexdigest(),
        context_contract_version="mesa-e2e.context.v2",
        source_context_contract="mesa-e2e.sealed-retrieval-context.v1",
    )

    # Freeze has transport_max_attempts = 2
    freeze_payload = {
        "runtime_identities": {
            "answer_transport": {
                "base_url": "https://api.nvidia.com/v1",
                "implementation": OpenAICompatibleHTTPTransport.implementation_id,
                "provider": "openai_compatible",
                "transport_max_attempts": 2,
                "timeout_seconds": 60.0,
            }
        }
    }

    # Config has answer_provider_transport_max_attempts = 3 (DRIFT)
    cfg = QualificationConfig(
        run_id=run_id,
        run_dir=run_dir,
        freeze_path=tmp_path / "freeze.json",
        checksum_path=tmp_path / "freeze.SHA256",
        repository_root=REPO,
        current_repository_shas={"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40},
        sqlite_path=tmp_path / "db.sqlite",
        lancedb_dir=tmp_path / "lance",
        kuzu_dir=tmp_path / "kuzu",
        answer_provider_base_url="https://api.nvidia.com/v1",
        answer_system_prompt="sys",
        answer_instruction="inst",
        answer_request_parameters={},
        answer_provider_timeout_seconds=60.0,
        answer_provider_transport_max_attempts=3,
    )

    with pytest.raises(QualificationRunnerError, match="retry policy transport_max_attempts differs"):
        _trusted_answer_transport(cfg, freeze_payload, authority)


# =========================================================================
# 3. TRANSPORT TIMEOUT RETRY + SUCCESS (Section 32)
# =========================================================================

def test_client_timeout_retry_then_success(tmp_path: Path):
    run_id = "RUN-TIMEOUT-01"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-TIMEOUT")

    class FlakyTimeoutTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            if self.calls == 1:
                raise ProviderTransportTimeoutError("simulated read timeout at 60s")
            return _valid_answer_payload("Answer arrived on attempt 2.")

    telemetry = ProviderReliabilityTelemetry()
    transport = FlakyTimeoutTransport()
    policy = ProviderRetryPolicy(transport_max_attempts=2, retry_backoff_seconds=0.0)

    capture = execute_answer_and_persist(
        store=store,
        context=ctx,
        question="What is the legal deadline?",
        system_prompt="system",
        answer_instruction="use context",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0, "max_tokens": 4096},
        transport=transport,
        timestamp_utc=NOW,
        retry_policy=policy,
        accounting=telemetry,
    )

    # Invariants verification
    assert transport.calls == 2
    assert capture.query_id == "Q-TIMEOUT"
    assert capture.parsed_response["answer"] == "Answer arrived on attempt 2."

    # Failed attempt preserved in raw evidence
    attempt1_file = store.raw_provider_dir / "Q-TIMEOUT.attempt_1.json"
    assert attempt1_file.exists()
    att1 = json.loads(attempt1_file.read_text())
    assert att1["attempt_number"] == 1
    assert att1["exception_category"] == "TRANSPORT_TIMEOUT"
    assert att1["content_present"] is False
    store._verify_seal(attempt1_file)

    # Successful attempt preserved in raw evidence
    attempt2_file = store.raw_provider_dir / "Q-TIMEOUT.attempt_2.json"
    assert attempt2_file.exists()
    att2 = json.loads(attempt2_file.read_text())
    assert att2["attempt_number"] == 2
    assert att2["exception_category"] is None
    assert att2["content_present"] is True
    store._verify_seal(attempt2_file)

    # Authoritative exchange reflects attempt lineage
    exchange_file = store.raw_provider_dir / "Q-TIMEOUT.json"
    assert exchange_file.exists()
    ex = json.loads(exchange_file.read_text())
    assert ex["authoritative_attempt_number"] == 2
    assert ex["total_attempts"] == 2
    assert len(ex["attempts"]) == 2

    # Accounting reflects all attempts
    assert telemetry.logical_answer_requests == 1
    assert telemetry.total_provider_attempts == 2
    assert telemetry.transport_retries == 1
    assert telemetry.transport_timeouts == 1
    assert telemetry.successful_requests == 1
    assert telemetry.failed_requests == 0


# =========================================================================
# 4. REPEATED TRANSPORT FAILURE EXHAUSTION (Section 33)
# =========================================================================

def test_repeated_transport_timeout_exhaustion(tmp_path: Path):
    run_id = "RUN-EXHAUST-01"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-EXHAUST")

    class AlwaysTimeoutTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            raise ProviderTransportTimeoutError(f"read timeout on attempt {self.calls}")

    telemetry = ProviderReliabilityTelemetry()
    transport = AlwaysTimeoutTransport()
    policy = ProviderRetryPolicy(transport_max_attempts=2, retry_backoff_seconds=0.0)

    with pytest.raises(ProviderTransportExhaustionError, match="exhausted \\(2/2\\)"):
        execute_answer_and_persist(
            store=store,
            context=ctx,
            question="What is the statute?",
            system_prompt="system",
            answer_instruction="use context",
            model="openai/gpt-oss-20b",
            request_parameters={"temperature": 0.0, "max_tokens": 4096},
            transport=transport,
            timestamp_utc=NOW,
            retry_policy=policy,
            accounting=telemetry,
        )

    assert transport.calls == 2
    # Verify no fabricated answer was created
    assert not (store.raw_answers_dir / "Q-EXHAUST.json").exists()
    # Verify both failed attempts are preserved
    assert (store.raw_provider_dir / "Q-EXHAUST.attempt_1.json").exists()
    assert (store.raw_provider_dir / "Q-EXHAUST.attempt_2.json").exists()
    assert telemetry.failed_requests == 1
    assert telemetry.total_provider_attempts == 2


# =========================================================================
# 5. INCOMPLETE LENGTH THEN SUCCESS (Section 34)
# =========================================================================

def test_incomplete_length_then_success(tmp_path: Path):
    run_id = "RUN-LENGTH-01"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-LEN-SUCCESS")

    class LengthThenSuccessTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            if self.calls == 1:
                # Real upstream shape: choices[0].message.content is None, finish_reason="length"
                return {
                    "id": "chatcmpl-call-1",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "reasoning": "Should NEVER be used or stored as answer evidence.",
                            },
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 500,
                        "completion_tokens": 4096,
                        "total_tokens": 4596,
                        "completion_tokens_details": {"reasoning_tokens": 4096},
                    },
                }
            return _valid_answer_payload("Valid answer on attempt 2.")

    telemetry = ProviderReliabilityTelemetry()
    transport = LengthThenSuccessTransport()
    policy = ProviderRetryPolicy(incomplete_completion_max_attempts=2, retry_backoff_seconds=0.0)

    capture = execute_answer_and_persist(
        store=store,
        context=ctx,
        question="What is the ruling?",
        system_prompt="system",
        answer_instruction="instruction",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0, "max_tokens": 4096},
        transport=transport,
        timestamp_utc=NOW,
        retry_policy=policy,
        accounting=telemetry,
    )

    assert transport.calls == 2
    assert capture.parsed_response["answer"] == "Valid answer on attempt 2."

    # First attempt preserved as incomplete
    att1 = json.loads((store.raw_provider_dir / "Q-LEN-SUCCESS.attempt_1.json").read_text())
    assert att1["exception_category"] == "INCOMPLETE_COMPLETION_TOKEN_LIMIT"
    assert att1["finish_reason"] == "length"
    assert att1["content_present"] is False
    assert att1["completion_tokens"] == 4096
    assert att1["reasoning_tokens"] == 4096
    # Invariant: raw reasoning text is NEVER stored
    assert "Should NEVER" not in json.dumps(att1)

    # Second attempt authoritative
    att2 = json.loads((store.raw_provider_dir / "Q-LEN-SUCCESS.attempt_2.json").read_text())
    assert att2["finish_reason"] == "stop"
    assert att2["content_present"] is True

    # Authoritative exchange has cumulative tokens
    ex = json.loads((store.raw_provider_dir / "Q-LEN-SUCCESS.json").read_text())
    assert ex["authoritative_attempt_number"] == 2
    assert ex["cumulative_token_usage"]["completion_tokens"] == 4096 + 45
    assert ex["cumulative_token_usage"]["total_tokens"] == 4596 + 165
    assert "Should NEVER" not in json.dumps(ex)

    assert telemetry.incomplete_completion_retries == 1
    assert telemetry.successful_requests == 1


# =========================================================================
# 6. REPEATED LENGTH EXHAUSTION (Section 35)
# =========================================================================

def test_repeated_length_exhaustion_fails_closed(tmp_path: Path):
    run_id = "RUN-LEN-EXHAUST"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-LEN-EX")

    class AlwaysLengthTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            return {
                "id": f"chatcmpl-loop-{self.calls}",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": "Reasoning loop text...",
                        },
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 4096,
                    "total_tokens": 4196,
                },
            }

    telemetry = ProviderReliabilityTelemetry()
    transport = AlwaysLengthTransport()
    policy = ProviderRetryPolicy(incomplete_completion_max_attempts=2, retry_backoff_seconds=0.0)

    with pytest.raises(ProviderIncompleteCompletionError, match="incomplete completion attempts exhausted \\(2/2\\)"):
        execute_answer_and_persist(
            store=store,
            context=ctx,
            question="What is the holding?",
            system_prompt="system",
            answer_instruction="instruction",
            model="openai/gpt-oss-20b",
            request_parameters={"temperature": 0.0, "max_tokens": 4096},
            transport=transport,
            timestamp_utc=NOW,
            retry_policy=policy,
            accounting=telemetry,
        )

    assert transport.calls == 2
    assert not (store.raw_answers_dir / "Q-LEN-EX.json").exists()
    assert (store.raw_provider_dir / "Q-LEN-EX.attempt_1.json").exists()
    assert (store.raw_provider_dir / "Q-LEN-EX.attempt_2.json").exists()
    assert telemetry.failed_requests == 1


# =========================================================================
# 7. NON-RETRYABLE 4XX (Section 36)
# =========================================================================

@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_non_retryable_4xx_fails_immediately_without_retry(tmp_path: Path, status_code: int):
    run_id = f"RUN-4XX-{status_code}"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-4XX")

    class Http4xxTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            raise ProviderRequestError(
                f"HTTP {status_code} Unauthorized/Bad Request",
                http_status=status_code,
            )

    transport = Http4xxTransport()
    policy = ProviderRetryPolicy(transport_max_attempts=3)

    with pytest.raises(ProviderRequestError) as exc_info:
        execute_answer_and_persist(
            store=store,
            context=ctx,
            question="What is the rule?",
            system_prompt="system",
            answer_instruction="instruction",
            model="openai/gpt-oss-20b",
            request_parameters={"temperature": 0.0},
            transport=transport,
            timestamp_utc=NOW,
            retry_policy=policy,
        )

    assert exc_info.value.http_status == status_code
    # Must fail on the first attempt with NO retries
    assert transport.calls == 1
    assert (store.raw_provider_dir / "Q-4XX.attempt_1.json").exists()
    assert not (store.raw_provider_dir / "Q-4XX.attempt_2.json").exists()


# =========================================================================
# 8. 429 AND RETRY-AFTER HANDLING (Section 37)
# =========================================================================

def test_parse_retry_after():
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("  12.5  ") == 12.5
    assert parse_retry_after("-1") is None
    assert parse_retry_after(None) is None
    assert parse_retry_after("invalid") is None
    # Bounded by max_seconds
    assert parse_retry_after("300", max_seconds=30.0) == 30.0


def test_429_retry_then_success(tmp_path: Path):
    run_id = "RUN-429-01"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-429")

    class RateLimitedTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            if self.calls == 1:
                raise ProviderRateLimitError(
                    "rate limit exceeded",
                    http_status=429,
                    retry_after=0.01,
                )
            return _valid_answer_payload("429 cleared answer.")

    transport = RateLimitedTransport()
    telemetry = ProviderReliabilityTelemetry()
    policy = ProviderRetryPolicy(transport_max_attempts=2, retry_backoff_seconds=0.0)

    capture = execute_answer_and_persist(
        store=store,
        context=ctx,
        question="What is the rule?",
        system_prompt="system",
        answer_instruction="instruction",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0},
        transport=transport,
        timestamp_utc=NOW,
        retry_policy=policy,
        accounting=telemetry,
    )

    assert transport.calls == 2
    assert capture.parsed_response["answer"] == "429 cleared answer."
    assert telemetry.rate_limits == 1
    assert telemetry.transport_retries == 1


# =========================================================================
# 9. 5XX TRANSIENT ERROR RETRY + SUCCESS (Section 38)
# =========================================================================

def test_5xx_transient_retry_then_success(tmp_path: Path):
    run_id = "RUN-5XX-01"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-5XX")

    class ServerErrorTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            if self.calls == 1:
                raise ProviderTemporaryServerError("503 Service Unavailable", http_status=503)
            return _valid_answer_payload("503 cleared answer.")

    transport = ServerErrorTransport()
    telemetry = ProviderReliabilityTelemetry()
    policy = ProviderRetryPolicy(transport_max_attempts=2, retry_backoff_seconds=0.0)

    capture = execute_answer_and_persist(
        store=store,
        context=ctx,
        question="What is the standard?",
        system_prompt="system",
        answer_instruction="instruction",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0},
        transport=transport,
        timestamp_utc=NOW,
        retry_policy=policy,
        accounting=telemetry,
    )

    assert transport.calls == 2
    assert capture.parsed_response["answer"] == "503 cleared answer."
    assert telemetry.server_errors == 1


# =========================================================================
# 10. REQUEST AND CONTEXT IDENTITY INVARIANCE (Sections 16, 22)
# =========================================================================

def test_request_identity_hash_invariant_across_attempts(tmp_path: Path):
    run_id = "RUN-INV-01"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-INV")

    class InvariantTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.calls = 0
            self.seen_request_hashes = []

        def complete(self, request_payload):
            self.calls += 1
            self.seen_request_hashes.append(
                hashlib.sha256(canonical_json_bytes(request_payload)).hexdigest()
            )
            if self.calls == 1:
                raise ProviderTransportTimeoutError("timeout 1")
            return _valid_answer_payload()

    transport = InvariantTransport()
    execute_answer_and_persist(
        store=store,
        context=ctx,
        question="What is the invariant?",
        system_prompt="system",
        answer_instruction="instruction",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0, "max_tokens": 4096},
        transport=transport,
        timestamp_utc=NOW,
        retry_policy=ProviderRetryPolicy(retry_backoff_seconds=0.0),
    )

    assert transport.calls == 2
    # Exact request hashes across attempt 1 and attempt 2 MUST be identical
    assert transport.seen_request_hashes[0] == transport.seen_request_hashes[1]

    # Verify attempt artifacts have identical request_hash and context_sha256
    att1 = json.loads((store.raw_provider_dir / "Q-INV.attempt_1.json").read_text())
    att2 = json.loads((store.raw_provider_dir / "Q-INV.attempt_2.json").read_text())
    assert att1["request_hash"] == att2["request_hash"]
    assert att1["context_sha256"] == att2["context_sha256"]
    assert att1["logical_request_hash"] == att2["logical_request_hash"]


# =========================================================================
# 11. FALSE-PASS ADVERSARIAL INTEGRITY TESTS (Section 52)
# =========================================================================

def test_adversarial_retry_cannot_mutate_temperature(tmp_path: Path):
    run_id = "RUN-ADV-TEMP"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-TEMP")

    class MutatingTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self, params):
            self.params = params
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            if self.calls == 1:
                # Malicious attempt to change temperature to break reasoning loop
                self.params["temperature"] = 0.7
                raise ProviderIncompleteCompletionError("loop", finish_reason="length")
            return _valid_answer_payload()

    params = {"temperature": 0.0, "max_tokens": 4096}
    transport = MutatingTransport(params)

    with pytest.raises(AnswerExecutionError, match="request mutated between provider attempts"):
        execute_answer_and_persist(
            store=store,
            context=ctx,
            question="What is temperature?",
            system_prompt="system",
            answer_instruction="instruction",
            model="openai/gpt-oss-20b",
            request_parameters=params,
            transport=transport,
            timestamp_utc=NOW,
            retry_policy=ProviderRetryPolicy(retry_backoff_seconds=0.0),
        )


def test_adversarial_retry_cannot_mutate_max_tokens(tmp_path: Path):
    run_id = "RUN-ADV-TOKENS"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-TOKENS")

    class MutatingTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self, params):
            self.params = params
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            if self.calls == 1:
                self.params["max_tokens"] = 8192
                raise ProviderIncompleteCompletionError("loop", finish_reason="length")
            return _valid_answer_payload()

    params = {"temperature": 0.0, "max_tokens": 4096}
    transport = MutatingTransport(params)

    with pytest.raises(AnswerExecutionError, match="request mutated between provider attempts"):
        execute_answer_and_persist(
            store=store,
            context=ctx,
            question="What are tokens?",
            system_prompt="system",
            answer_instruction="instruction",
            model="openai/gpt-oss-20b",
            request_parameters=params,
            transport=transport,
            timestamp_utc=NOW,
            retry_policy=ProviderRetryPolicy(retry_backoff_seconds=0.0),
        )


def test_adversarial_retry_cannot_mutate_context(tmp_path: Path):
    run_id = "RUN-ADV-CTX"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-CTX")

    class MutatingContextTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self, context_obj):
            self.ctx = context_obj
            self.calls = 0

        def complete(self, request_payload):
            self.calls += 1
            if self.calls == 1:
                # Mutate context on the fly
                object.__setattr__(self.ctx, "exact_model_visible_context", "mutated context!")
                raise ProviderIncompleteCompletionError("loop", finish_reason="length")
            return _valid_answer_payload()

    transport = MutatingContextTransport(ctx)

    with pytest.raises(AnswerExecutionError, match="context mutated between provider attempts"):
        execute_answer_and_persist(
            store=store,
            context=ctx,
            question="What is context?",
            system_prompt="system",
            answer_instruction="instruction",
            model="openai/gpt-oss-20b",
            request_parameters={"temperature": 0.0},
            transport=transport,
            timestamp_utc=NOW,
            retry_policy=ProviderRetryPolicy(retry_backoff_seconds=0.0),
        )


def test_adversarial_reasoning_text_never_used_as_answer(tmp_path: Path):
    run_id = "RUN-ADV-REASON"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()
    ctx = _make_context(run_id=run_id, query_id="Q-REASON")

    # Provider returns null content, but reasoning contains the correct JSON answer
    correct_json = json.dumps(
        {
            "answer": "This answer is inside reasoning string!",
            "evidence_chunk_ids": ["chunk-001"],
            "insufficient_evidence": False,
            "claims": [],
        }
    )

    class ReasoningTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def complete(self, request_payload):
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": correct_json,
                        },
                        "finish_reason": "length",
                    }
                ]
            }

    # Must fail closed with ProviderIncompleteCompletionError and MUST NOT parse reasoning
    with pytest.raises(ProviderIncompleteCompletionError):
        execute_answer_and_persist(
            store=store,
            context=ctx,
            question="What is inside reasoning?",
            system_prompt="system",
            answer_instruction="instruction",
            model="openai/gpt-oss-20b",
            request_parameters={"temperature": 0.0},
            transport=ReasoningTransport(),
            timestamp_utc=NOW,
            retry_policy=ProviderRetryPolicy(incomplete_completion_max_attempts=1),
        )


def test_retry_counter_resets_per_logical_query(tmp_path: Path):
    """Section 47: Retry budget must reset per logical query so earlier retries don't starve later ones."""
    run_id = "RUN-PER-QUERY-01"
    store = RunArtifactStore(tmp_path / run_id, run_id)
    store.initialize()

    class FlakyPerQueryTransport:
        provider_name = "openai_compatible"
        base_url = "https://api.nvidia.com/v1"

        def __init__(self):
            self.query_attempts = {}

        def complete(self, request_payload):
            # Each query fails attempt 1 with timeout, then succeeds on attempt 2
            # Identify query from prompt
            user_msg = request_payload["messages"][1]["content"]
            qid = "Q1" if "Q1" in user_msg else "Q2"
            self.query_attempts[qid] = self.query_attempts.get(qid, 0) + 1
            if self.query_attempts[qid] == 1:
                raise ProviderTransportTimeoutError(f"transient timeout on {qid}")
            return _valid_answer_payload(f"Answer for {qid}")

    transport = FlakyPerQueryTransport()
    policy = ProviderRetryPolicy(transport_max_attempts=2, retry_backoff_seconds=0.0)

    # Q1: uses 2 attempts (1 retry) -> succeeds
    ctx1 = _make_context(run_id=run_id, query_id="Q1", context_text="Context for Q1")
    cap1 = execute_answer_and_persist(
        store=store,
        context=ctx1,
        question="Question Q1",
        system_prompt="sys",
        answer_instruction="inst",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0},
        transport=transport,
        timestamp_utc=NOW,
        retry_policy=policy,
    )
    assert cap1.parsed_response["answer"] == "Answer for Q1"
    assert transport.query_attempts["Q1"] == 2

    # Q2: must ALSO receive its full attempt budget of 2, not 0!
    ctx2 = _make_context(run_id=run_id, query_id="Q2", context_text="Context for Q2")
    cap2 = execute_answer_and_persist(
        store=store,
        context=ctx2,
        question="Question Q2",
        system_prompt="sys",
        answer_instruction="inst",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0},
        transport=transport,
        timestamp_utc=NOW,
        retry_policy=policy,
    )
    assert cap2.parsed_response["answer"] == "Answer for Q2"
    assert transport.query_attempts["Q2"] == 2


# =========================================================================
# 12. OFFICIAL EXECUTION SESSION EVIDENCE LINEAGE (Section 41)
# =========================================================================

def test_official_execution_session_registers_attempt_lineage(tmp_path: Path):
    run_id = "RUN-EXEC-LINEAGE-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)

    http_transport = OpenAICompatibleHTTPTransport(
        base_url="https://api.nvidia.com/v1",
        api_key="secret-key",
        timeout_seconds=60.0,
    )

    mesa_transport = TrustedMESATransport(
        MESATransportConfig(
            base_url="http://127.0.0.1:18000",
            api_key="secret-mesa-key",
            timeout_seconds=30.0,
            api_version="v4",
            expected_mesa_sha="a" * 40,
            runtime_profile="combined",
        )
    )
    session = _begin_official_execution(
        run_id=run_id,
        run_dir=run_dir,
        freeze_sha256="0" * 64,
        mesa_sha="a" * 40,
        transport=mesa_transport,
        answer_transport=http_transport,
    )
    store = RunArtifactStore(run_dir, run_id, execution_session=session)
    store.initialize()
    session.write_execution_record()
    session.start_capture()

    ctx = _make_context(run_id=run_id, query_id="Q-LINEAGE")

    # Create dummy trusted context artifact so register_answer_artifact succeeds
    context_raw_path = store.persist_raw_context(
        query_id="Q-LINEAGE",
        request={"q": "test"},
        response={"context": ctx.exact_model_visible_context},
        transport_status=200,
        timestamp_utc=NOW,
        latency_ms=10.0,
        execution_id=session.execution_id,
    )
    session._raw_records["raw/context/Q-LINEAGE.json"] = {
        "path": "raw/context/Q-LINEAGE.json",
        "sha256": store._verify_seal(context_raw_path),
        "capture_id": "test-context-capture-id",
        "collector": "test",
        "source": "trusted_mesa_transport",
        "endpoint": "GET /v4/sessions/test/context",
        "transport_status": 200,
        "request_sha256": "0" * 64,
        "response_sha256": "0" * 64,
        **session.public_binding(),
    }
    session._raw_records["raw/context/Q-LINEAGE.json"]["capture_attestation"] = session._sign(
        session._raw_records["raw/context/Q-LINEAGE.json"]
    )

    # Mock HTTP transport complete to fail once on timeout then succeed
    orig_complete = http_transport.complete
    calls = 0

    def mock_complete(req):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderTransportTimeoutError("attempt 1 timeout")
        # generate valid response and register exchange receipt
        resp = _valid_answer_payload("Sealed official answer.")
        req_sha = hashlib.sha256(canonical_json_bytes(req)).hexdigest()
        resp_sha = hashlib.sha256(canonical_json_bytes(resp)).hexdigest()
        cap_id = hashlib.sha256(canonical_json_bytes({"p": "openai_compatible", "q": req_sha, "r": resp_sha})).hexdigest()
        http_transport._verified_exchanges.setdefault((req_sha, resp_sha), []).append(cap_id)
        return resp

    http_transport.complete = mock_complete

    capture = execute_answer_and_persist(
        store=store,
        context=ctx,
        question="What is official provenance?",
        system_prompt="sys",
        answer_instruction="inst",
        model="openai/gpt-oss-20b",
        request_parameters={"temperature": 0.0},
        transport=http_transport,
        timestamp_utc=NOW,
        execution_session=session,
        context_raw_path=context_raw_path,
        retry_policy=ProviderRetryPolicy(retry_backoff_seconds=0.0),
    )

    assert capture.parsed_response["answer"] == "Sealed official answer."

    # Compute raw manifest and verify official attestation
    manifest = store.compute_raw_manifest(session)
    assert manifest["execution_mode"] == "official"
    session.verify_raw_manifest(manifest, manifest["manifest_hash"])

    manifest_paths = [e["path"] for e in manifest["entries"]]
    # Attempt 1, Attempt 2, authoritative provider exchange, context, and answer MUST all be in manifest
    assert "raw/provider/Q-LINEAGE.attempt_1.json" in manifest_paths
    assert "raw/provider/Q-LINEAGE.attempt_2.json" in manifest_paths
    assert "raw/provider/Q-LINEAGE.json" in manifest_paths
    assert "raw/answers/Q-LINEAGE.json" in manifest_paths
    assert "raw/context/Q-LINEAGE.json" in manifest_paths
