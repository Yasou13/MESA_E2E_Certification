"""Exact OpenAI-compatible answer execution, bounded reliability, and raw-first capture."""

from __future__ import annotations

import hashlib
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

from harness.artifacts import (
    CertifiedAnswerExecutionCapture,
    RunArtifactStore,
    _sha256_bytes,
    canonical_json_bytes,
)
from harness.mesa_adapters import NormalizedContextCapture
from harness.models import AnswerResponse


class AnswerExecutionError(RuntimeError):
    """Base error for all answer execution and provider boundary failures."""

    pass


class ProviderExecutionError(AnswerExecutionError):
    """Base error for upstream provider failures with safe operational metadata."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        category: str = "PROVIDER_ERROR",
        **kwargs: Any,
    ):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.category = category
        for k, v in kwargs.items():
            setattr(self, k, v)


class ProviderTransportError(ProviderExecutionError):
    """Transport / infrastructure error during provider communication."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        category: str = "TRANSPORT_ERROR",
        retry_after: float | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, http_status=http_status, category=category, **kwargs)
        self.retry_after = retry_after
        self.headers = headers or {}


class ProviderTransportTimeoutError(ProviderTransportError):
    """Remote provider read or connection timeout at transport layer."""

    def __init__(self, message: str, *, http_status: int | None = None, **kwargs: Any):
        super().__init__(
            message, http_status=http_status, category="TRANSPORT_TIMEOUT", **kwargs
        )


class ProviderRateLimitError(ProviderTransportError):
    """Provider returned HTTP 429 Too Many Requests."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = 429,
        retry_after: float | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            message,
            http_status=http_status,
            category="RATE_LIMIT",
            retry_after=retry_after,
            headers=headers,
            **kwargs,
        )


class ProviderTemporaryServerError(ProviderTransportError):
    """Provider returned transient 5xx server error."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = 500,
        retry_after: float | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            message,
            http_status=http_status,
            category="TEMPORARY_SERVER_ERROR",
            retry_after=retry_after,
            headers=headers,
            **kwargs,
        )


class ProviderTransportConnectionError(ProviderTransportError):
    """Connection reset, connection refused, or broken socket at transport layer."""

    def __init__(self, message: str, *, http_status: int | None = None, **kwargs: Any):
        super().__init__(
            message, http_status=http_status, category="CONNECTION_ERROR", **kwargs
        )


class ProviderTransportExhaustionError(ProviderTransportError):
    """All permitted bounded transport retry attempts have been exhausted."""

    def __init__(self, message: str, *, http_status: int | None = None, **kwargs: Any):
        super().__init__(
            message,
            http_status=http_status,
            category="TRANSPORT_ATTEMPTS_EXHAUSTED",
            **kwargs,
        )


class ProviderRequestError(ProviderExecutionError):
    """Non-retryable deterministic 4xx client/request error (e.g. 400, 401, 403)."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            message, http_status=http_status, category="REQUEST_ERROR", **kwargs
        )
        self.headers = headers or {}


class ProviderResponseError(ProviderExecutionError):
    """Provider completed HTTP exchange but response payload is structurally invalid or incomplete."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = 200,
        category: str = "RESPONSE_ERROR",
        finish_reason: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, http_status=http_status, category=category, **kwargs)
        self.finish_reason = finish_reason
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.reasoning_tokens = reasoning_tokens


class ProviderIncompleteCompletionError(ProviderResponseError):
    """Generation ended due to token limit before valid content was emitted (finish_reason=length, content=None)."""

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(
            message, category="INCOMPLETE_COMPLETION_TOKEN_LIMIT", **kwargs
        )


class ProviderEmptyCompletionError(ProviderResponseError):
    """Provider finished generation with stop/other finish_reason but null content."""

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(message, category="EMPTY_COMPLETION", **kwargs)


class ProviderEmptyContentError(ProviderResponseError):
    """Provider message content was an empty string."""

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(message, category="EMPTY_CONTENT", **kwargs)


class ProviderNonStringContentError(ProviderResponseError):
    """Provider message content was not a string."""

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(message, category="NON_STRING_CONTENT", **kwargs)


class ProviderMalformedResponseError(ProviderResponseError):
    """Provider response body was not valid JSON or lacked required choices structure."""

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(message, category="MALFORMED_RESPONSE", **kwargs)


class ProviderSchemaValidationError(ProviderResponseError):
    """Provider message content string failed AnswerResponse schema validation."""

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(message, category="ANSWER_SCHEMA_VALIDATION_ERROR", **kwargs)


@dataclass(frozen=True)
class ProviderRetryPolicy:
    """Explicit, typed, deterministic retry policy frozen for qualification execution."""

    timeout_seconds: float = 60.0
    transport_max_attempts: int = 2
    incomplete_completion_max_attempts: int = 2
    retry_backoff_seconds: float = 1.0
    max_retry_after_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.transport_max_attempts < 1:
            raise ValueError("transport_max_attempts must be at least 1")
        if self.incomplete_completion_max_attempts < 1:
            raise ValueError("incomplete_completion_max_attempts must be at least 1")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        if self.max_retry_after_seconds < 0:
            raise ValueError("max_retry_after_seconds cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "transport_max_attempts": self.transport_max_attempts,
            "incomplete_completion_max_attempts": self.incomplete_completion_max_attempts,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "max_retry_after_seconds": self.max_retry_after_seconds,
        }


@dataclass
class ProviderReliabilityTelemetry:
    """Non-scoring operational metrics tracking provider attempts, retries, and token accounting."""

    logical_answer_requests: int = 0
    total_provider_attempts: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    transport_retries: int = 0
    incomplete_completion_retries: int = 0
    transport_timeouts: int = 0
    rate_limits: int = 0
    server_errors: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_reasoning_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_answer_requests": self.logical_answer_requests,
            "total_provider_attempts": self.total_provider_attempts,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "transport_retries": self.transport_retries,
            "incomplete_completion_retries": self.incomplete_completion_retries,
            "transport_timeouts": self.transport_timeouts,
            "rate_limits": self.rate_limits,
            "server_errors": self.server_errors,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
        }


def parse_retry_after(header_value: str | None, max_seconds: float = 30.0) -> float | None:
    """Safely parse HTTP Retry-After header as seconds or HTTP-date, bounded by max_seconds."""
    if not header_value:
        return None
    header_str = header_value.strip()
    try:
        seconds = float(header_str)
        if seconds < 0:
            return None
        return min(seconds, max_seconds)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(header_str)
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        if delta < 0:
            return 0.0
        return min(delta, max_seconds)
    except Exception:
        return None


def classify_provider_response(
    raw_response: Any,
) -> tuple[str, str | None, dict[str, int | None]]:
    """Strictly classify provider response structure and extract safe metadata only.

    CRITICAL INVARIANT: Provider chain-of-thought/reasoning text is NEVER inspected,
    parsed, salvaged, or returned as answer evidence.
    """
    if not isinstance(raw_response, dict):
        raise ProviderMalformedResponseError("provider response must be a JSON object")
    if "choices" not in raw_response:
        raise ProviderMalformedResponseError("provider response lacks choices")
    choices = raw_response["choices"]
    if not isinstance(choices, list) or len(choices) == 0:
        raise ProviderMalformedResponseError("provider response choices must be a non-empty list")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderMalformedResponseError("provider response choice must be an object")
    if "message" not in choice or not isinstance(choice["message"], dict):
        raise ProviderMalformedResponseError("provider response choice lacks message object")
    message = choice["message"]
    finish_reason = choice.get("finish_reason")

    # Safe token usage extraction (integers only)
    usage = raw_response.get("usage")
    usage_info: dict[str, int | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
    }
    if isinstance(usage, dict):
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            v = usage.get(k)
            if isinstance(v, int):
                usage_info[k] = v
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            rt = details.get("reasoning_tokens")
            if isinstance(rt, int):
                usage_info["reasoning_tokens"] = rt

    content = message.get("content")

    if content is None:
        if finish_reason == "length":
            raise ProviderIncompleteCompletionError(
                "provider generation ended due to token limit before final content "
                "(finish_reason=length, content=None)",
                finish_reason="length",
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
                total_tokens=usage_info["total_tokens"],
                reasoning_tokens=usage_info["reasoning_tokens"],
            )
        if finish_reason == "stop":
            raise ProviderEmptyCompletionError(
                "provider returned finish_reason=stop with null content",
                finish_reason="stop",
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
                total_tokens=usage_info["total_tokens"],
                reasoning_tokens=usage_info["reasoning_tokens"],
            )
        raise ProviderMalformedResponseError(
            f"provider returned null content with finish_reason={finish_reason!r}",
            finish_reason=finish_reason,
            prompt_tokens=usage_info["prompt_tokens"],
            completion_tokens=usage_info["completion_tokens"],
            total_tokens=usage_info["total_tokens"],
            reasoning_tokens=usage_info["reasoning_tokens"],
        )

    if not isinstance(content, str):
        raise ProviderNonStringContentError(
            f"provider message content must be a string, got {type(content).__name__}",
            finish_reason=finish_reason,
            prompt_tokens=usage_info["prompt_tokens"],
            completion_tokens=usage_info["completion_tokens"],
            total_tokens=usage_info["total_tokens"],
            reasoning_tokens=usage_info["reasoning_tokens"],
        )

    if content == "":
        raise ProviderEmptyContentError(
            "provider message content is empty",
            finish_reason=finish_reason,
            prompt_tokens=usage_info["prompt_tokens"],
            completion_tokens=usage_info["completion_tokens"],
            total_tokens=usage_info["total_tokens"],
            reasoning_tokens=usage_info["reasoning_tokens"],
        )

    return content, finish_reason, usage_info


def _parse_openai_compatible_response(raw_response: dict[str, Any]) -> AnswerResponse:
    content, _finish_reason, _usage = classify_provider_response(raw_response)
    try:
        return AnswerResponse.model_validate_json(content)
    except Exception as exc:
        raise ProviderSchemaValidationError(
            f"provider answer does not satisfy AnswerResponse: {exc}"
        ) from exc


class ProviderTransport(Protocol):
    provider_name: str

    def complete(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenAICompatibleHTTPTransport:
    """Minimal production transport with explicit bounded timeout and robust error classification."""

    implementation_id = "harness.answer_execution.urllib-openai-compatible.v1"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float,
        retry_policy: ProviderRetryPolicy | None = None,
        provider: str = "openai_compatible",
    ):
        if not (base_url.startswith("https://") or base_url.startswith("http://")):
            raise ValueError("provider base_url must use HTTP or HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.provider_name = provider
        self._base_url = base_url.rstrip("/")
        self._url = self._base_url + "/chat/completions"
        self._api_key = api_key
        self._timeout = float(timeout_seconds)
        self._retry_policy = retry_policy or ProviderRetryPolicy(timeout_seconds=self._timeout)
        self._verified_exchanges: dict[tuple[str, str], list[str]] = {}
        self.identity_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "implementation": self.implementation_id,
                    "provider": self.provider_name,
                    "base_url": self._base_url,
                }
            )
        ).hexdigest()

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def timeout_seconds(self) -> float:
        return self._timeout

    @property
    def retry_policy(self) -> ProviderRetryPolicy:
        return self._retry_policy

    def complete(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        body = canonical_json_bytes(request_payload)
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            self._url,
            data=body,
            headers=headers,
            method="POST",
        )
        status_code: int | None = None
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                status_code = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            headers = dict(exc.headers) if hasattr(exc, "headers") else {}
            retry_after = parse_retry_after(headers.get("Retry-After") or headers.get("retry-after"))
            if status_code == 429:
                raise ProviderRateLimitError(
                    f"provider rate limit (HTTP 429): {exc.reason}",
                    http_status=429,
                    retry_after=retry_after,
                    headers=headers,
                ) from exc
            if status_code in {500, 502, 503, 504}:
                raise ProviderTemporaryServerError(
                    f"provider server error (HTTP {status_code}): {exc.reason}",
                    http_status=status_code,
                    retry_after=retry_after,
                    headers=headers,
                ) from exc
            raise ProviderRequestError(
                f"provider request error (HTTP {status_code}): {exc.reason}",
                http_status=status_code,
                headers=headers,
            ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            reason = getattr(exc, "reason", None)
            reason_str = str(reason or exc).lower()
            if isinstance(exc, TimeoutError) or isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in reason_str:
                raise ProviderTransportTimeoutError(
                    f"provider request timed out after {self._timeout}s: {exc}",
                    http_status=None,
                ) from exc
            raise ProviderTransportConnectionError(
                f"provider connection error: {exc}",
                http_status=None,
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderMalformedResponseError(
                f"provider returned invalid JSON: {exc}",
                http_status=status_code or 200,
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderMalformedResponseError(
                "provider response must be a JSON object",
                http_status=status_code or 200,
            )
        request_sha = hashlib.sha256(canonical_json_bytes(request_payload)).hexdigest()
        response_sha = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        capture_id = hashlib.sha256(
            canonical_json_bytes(
                {
                    "provider": self.provider_name,
                    "request_sha256": request_sha,
                    "response_sha256": response_sha,
                }
            )
        ).hexdigest()
        self._verified_exchanges.setdefault((request_sha, response_sha), []).append(
            capture_id
        )
        return payload

    def consume_exchange_receipt(
        self, request_payload: dict[str, Any], response_payload: dict[str, Any]
    ) -> str:
        key = (
            hashlib.sha256(canonical_json_bytes(request_payload)).hexdigest(),
            hashlib.sha256(canonical_json_bytes(response_payload)).hexdigest(),
        )
        receipts = self._verified_exchanges.get(key)
        if not receipts:
            raise AnswerExecutionError(
                "provider exchange lacks a runner-owned HTTP receipt"
            )
        capture_id = receipts.pop(0)
        if not receipts:
            self._verified_exchanges.pop(key, None)
        return capture_id


def execute_answer_and_persist(
    *,
    store: RunArtifactStore,
    context: NormalizedContextCapture,
    question: str,
    system_prompt: str,
    answer_instruction: str,
    model: str,
    request_parameters: dict[str, Any],
    transport: ProviderTransport,
    timestamp_utc: datetime | None = None,
    execution_session: Any | None = None,
    context_raw_path: Path | None = None,
    retry_policy: ProviderRetryPolicy | None = None,
    accounting: ProviderReliabilityTelemetry | None = None,
) -> CertifiedAnswerExecutionCapture:
    """Execute provider request under bounded frozen retry policy and seal attempt lineage."""

    if context.run_id != store.run_id:
        raise AnswerExecutionError("context/store run_id mismatch")
    forbidden = {
        "expectedanswer",
        "expectedanswers",
        "expectedlabel",
        "expectedstatus",
        "requiredfact",
        "requiredfacts",
        "forbiddenclaim",
        "forbiddenclaims",
        "goldevidenceid",
        "goldevidenceids",
        "qrel",
        "qrels",
    }
    reserved = {"messages", "model"}

    def normalized_key(value: object) -> str:
        return "".join(
            character for character in str(value).casefold() if character.isalnum()
        )

    def validate_request_value(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = normalized_key(key)
                if normalized in forbidden:
                    raise AnswerExecutionError(
                        f"oracle/grader field is forbidden from provider request: {path}.{key}"
                    )
                validate_request_value(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                validate_request_value(nested, f"{path}[{index}]")

    request_keys = {str(key).casefold() for key in request_parameters}
    if request_keys & reserved:
        raise AnswerExecutionError(
            "model/messages cannot be overridden by request parameters"
        )
    validate_request_value(request_parameters, "request_parameters")

    policy = retry_policy or getattr(transport, "retry_policy", None) or ProviderRetryPolicy()

    user_prompt = (
        f"{answer_instruction}\n\nQUESTION:\n{question}\n\n"
        f"MODEL_VISIBLE_CONTEXT:\n{context.exact_model_visible_context}"
    )
    exact_request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **request_parameters,
    }

    # Deterministic request & context identities
    context_sha256 = _sha256_bytes(context.exact_model_visible_context.encode("utf-8"))
    request_sha256 = _sha256_bytes(canonical_json_bytes(exact_request))
    logical_request_id = f"{store.run_id}:{context.query_id}:answer_request"
    base_url = getattr(transport, "base_url", None) or getattr(transport, "_base_url", "")
    logical_request_hash = _sha256_bytes(
        canonical_json_bytes(
            {
                "run_id": store.run_id,
                "query_id": context.query_id,
                "logical_request_id": logical_request_id,
                "model": model,
                "base_url": base_url,
                "request_sha256": request_sha256,
                "context_sha256": context_sha256,
            }
        )
    )

    if accounting is not None:
        accounting.logical_answer_requests += 1

    attempt_number = 1
    transport_attempts = 0
    incomplete_attempts = 0
    attempt_records: list[dict[str, Any]] = []

    authoritative_raw_response: dict[str, Any] | None = None
    authoritative_parsed: AnswerResponse | None = None
    authoritative_attempt_number: int | None = None
    capture_time = timestamp_utc or datetime.now(timezone.utc)

    while True:
        # Request & context identity invariance checks (Sections 16, 22, 44, 45)
        curr_user_prompt = (
            f"{answer_instruction}\n\nQUESTION:\n{question}\n\n"
            f"MODEL_VISIBLE_CONTEXT:\n{context.exact_model_visible_context}"
        )
        curr_exact_request = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": curr_user_prompt},
            ],
            **request_parameters,
        }
        curr_context_sha = _sha256_bytes(context.exact_model_visible_context.encode("utf-8"))
        curr_request_sha = _sha256_bytes(canonical_json_bytes(curr_exact_request))
        curr_base_url = getattr(transport, "base_url", None) or getattr(transport, "_base_url", "")
        if curr_context_sha != context_sha256:
            raise AnswerExecutionError("context mutated between provider attempts")
        if curr_request_sha != request_sha256:
            raise AnswerExecutionError("request mutated between provider attempts")
        if curr_base_url != base_url:
            raise AnswerExecutionError("endpoint drifted between provider attempts")
        if model != curr_exact_request.get("model"):
            raise AnswerExecutionError("model drifted between provider attempts")

        if accounting is not None:
            accounting.total_provider_attempts += 1

        start_time = datetime.now(timezone.utc)
        start_mono = time.monotonic()
        raw_response: dict[str, Any] | None = None
        attempt_exc: Exception | None = None

        try:
            raw_response = transport.complete(dict(curr_exact_request))
        except Exception as exc:
            attempt_exc = exc

        end_time = datetime.now(timezone.utc)
        elapsed_seconds = max(0.0, time.monotonic() - start_mono)

        if attempt_exc is not None and not isinstance(attempt_exc, ProviderIncompleteCompletionError):
            # Handle Transport Layer Failure
            transport_attempts += 1
            is_timeout = isinstance(attempt_exc, ProviderTransportTimeoutError)
            is_ratelimit = isinstance(attempt_exc, ProviderRateLimitError)
            is_server_err = isinstance(attempt_exc, ProviderTemporaryServerError)
            is_conn_err = isinstance(attempt_exc, ProviderTransportConnectionError)

            http_status = getattr(attempt_exc, "http_status", None)
            category = getattr(attempt_exc, "category", "TRANSPORT_ERROR")
            if not isinstance(attempt_exc, ProviderTransportError):
                if isinstance(attempt_exc, (TimeoutError, socket.timeout)) or "timeout" in str(attempt_exc).lower():
                    is_timeout = True
                    category = "TRANSPORT_TIMEOUT"
                elif isinstance(attempt_exc, ConnectionResetError):
                    is_conn_err = True
                    category = "CONNECTION_ERROR"

            if accounting is not None:
                if is_timeout:
                    accounting.transport_timeouts += 1
                elif is_ratelimit:
                    accounting.rate_limits += 1
                elif is_server_err:
                    accounting.server_errors += 1

            attempt_record = {
                "schema_version": "1.0",
                "run_id": store.run_id,
                "lane": "provider_attempt",
                "query_id": context.query_id,
                "logical_answer_request_id": logical_request_id,
                "attempt_number": attempt_number,
                "request_hash": request_sha256,
                "context_sha256": context_sha256,
                "logical_request_hash": logical_request_hash,
                "provider": transport.provider_name,
                "model": model,
                "start_timestamp_utc": start_time.isoformat(),
                "end_timestamp_utc": end_time.isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "http_status": http_status,
                "exception_category": category,
                "finish_reason": None,
                "content_present": False,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "reasoning_tokens": None,
            }
            attempt_records.append(attempt_record)

            attempt_path, _ = store.persist_raw_provider_attempt(
                query_id=context.query_id,
                attempt_number=attempt_number,
                timestamp_utc=start_time,
                attempt_payload=attempt_record,
            )
            if execution_session is not None:
                execution_session.register_provider_attempt_artifact(
                    attempt_path,
                    attempt_record=attempt_record,
                    collector="harness.answer_execution.provider_boundary",
                )

            is_retryable = is_timeout or is_ratelimit or is_server_err or is_conn_err
            if not is_retryable:
                if accounting is not None:
                    accounting.failed_requests += 1
                raise attempt_exc

            if transport_attempts < policy.transport_max_attempts:
                if accounting is not None:
                    accounting.transport_retries += 1
                delay = getattr(attempt_exc, "retry_after", None)
                if delay is None or delay <= 0:
                    delay = policy.retry_backoff_seconds
                else:
                    delay = min(delay, policy.max_retry_after_seconds)
                if delay > 0:
                    time.sleep(delay)
                attempt_number += 1
                continue
            else:
                if accounting is not None:
                    accounting.failed_requests += 1
                raise ProviderTransportExhaustionError(
                    f"provider transport attempts exhausted ({transport_attempts}/{policy.transport_max_attempts}): {attempt_exc}"
                ) from attempt_exc

        # HTTP response payload was received (or incomplete error was raised)
        try:
            if isinstance(attempt_exc, ProviderIncompleteCompletionError):
                raise attempt_exc
            content, finish_reason, usage = classify_provider_response(raw_response)
            parsed = AnswerResponse.model_validate_json(content)

            attempt_record = {
                "schema_version": "1.0",
                "run_id": store.run_id,
                "lane": "provider_attempt",
                "query_id": context.query_id,
                "logical_answer_request_id": logical_request_id,
                "attempt_number": attempt_number,
                "request_hash": request_sha256,
                "context_sha256": context_sha256,
                "logical_request_hash": logical_request_hash,
                "provider": transport.provider_name,
                "model": model,
                "start_timestamp_utc": start_time.isoformat(),
                "end_timestamp_utc": end_time.isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "http_status": 200,
                "exception_category": None,
                "finish_reason": finish_reason or "stop",
                "content_present": True,
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["total_tokens"],
                "reasoning_tokens": usage["reasoning_tokens"],
            }
            attempt_records.append(attempt_record)
            attempt_path, _ = store.persist_raw_provider_attempt(
                query_id=context.query_id,
                attempt_number=attempt_number,
                timestamp_utc=start_time,
                attempt_payload=attempt_record,
            )
            if execution_session is not None:
                execution_session.register_provider_attempt_artifact(
                    attempt_path,
                    attempt_record=attempt_record,
                    collector="harness.answer_execution.provider_boundary",
                )

            authoritative_raw_response = raw_response
            authoritative_parsed = parsed
            authoritative_attempt_number = attempt_number
            if accounting is not None:
                accounting.successful_requests += 1
                if usage["prompt_tokens"]:
                    accounting.total_prompt_tokens += usage["prompt_tokens"]
                if usage["completion_tokens"]:
                    accounting.total_completion_tokens += usage["completion_tokens"]
                if usage["total_tokens"]:
                    accounting.total_tokens += usage["total_tokens"]
                if usage["reasoning_tokens"]:
                    accounting.total_reasoning_tokens += usage["reasoning_tokens"]
            break

        except ProviderIncompleteCompletionError as inc_exc:
            incomplete_attempts += 1
            attempt_record = {
                "schema_version": "1.0",
                "run_id": store.run_id,
                "lane": "provider_attempt",
                "query_id": context.query_id,
                "logical_answer_request_id": logical_request_id,
                "attempt_number": attempt_number,
                "request_hash": request_sha256,
                "context_sha256": context_sha256,
                "logical_request_hash": logical_request_hash,
                "provider": transport.provider_name,
                "model": model,
                "start_timestamp_utc": start_time.isoformat(),
                "end_timestamp_utc": end_time.isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "http_status": 200,
                "exception_category": "INCOMPLETE_COMPLETION_TOKEN_LIMIT",
                "finish_reason": "length",
                "content_present": False,
                "prompt_tokens": inc_exc.prompt_tokens,
                "completion_tokens": inc_exc.completion_tokens,
                "total_tokens": inc_exc.total_tokens,
                "reasoning_tokens": inc_exc.reasoning_tokens,
            }
            attempt_records.append(attempt_record)
            attempt_path, _ = store.persist_raw_provider_attempt(
                query_id=context.query_id,
                attempt_number=attempt_number,
                timestamp_utc=start_time,
                attempt_payload=attempt_record,
            )
            if execution_session is not None:
                execution_session.register_provider_attempt_artifact(
                    attempt_path,
                    attempt_record=attempt_record,
                    collector="harness.answer_execution.provider_boundary",
                )

            if accounting is not None:
                if inc_exc.prompt_tokens:
                    accounting.total_prompt_tokens += inc_exc.prompt_tokens
                if inc_exc.completion_tokens:
                    accounting.total_completion_tokens += inc_exc.completion_tokens
                if inc_exc.total_tokens:
                    accounting.total_tokens += inc_exc.total_tokens
                if inc_exc.reasoning_tokens:
                    accounting.total_reasoning_tokens += inc_exc.reasoning_tokens

            if incomplete_attempts < policy.incomplete_completion_max_attempts:
                if accounting is not None:
                    accounting.incomplete_completion_retries += 1
                delay = policy.retry_backoff_seconds
                if delay > 0:
                    time.sleep(delay)
                attempt_number += 1
                continue
            else:
                if accounting is not None:
                    accounting.failed_requests += 1
                raise ProviderIncompleteCompletionError(
                    f"provider incomplete completion attempts exhausted ({incomplete_attempts}/{policy.incomplete_completion_max_attempts}): {inc_exc}"
                ) from inc_exc

        except Exception as other_exc:
            # Non-retryable response condition (e.g. malformed JSON, schema violation, stop+null)
            attempt_record = {
                "schema_version": "1.0",
                "run_id": store.run_id,
                "lane": "provider_attempt",
                "query_id": context.query_id,
                "logical_answer_request_id": logical_request_id,
                "attempt_number": attempt_number,
                "request_hash": request_sha256,
                "context_sha256": context_sha256,
                "logical_request_hash": logical_request_hash,
                "provider": transport.provider_name,
                "model": model,
                "start_timestamp_utc": start_time.isoformat(),
                "end_timestamp_utc": end_time.isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "http_status": getattr(other_exc, "http_status", 200),
                "exception_category": getattr(other_exc, "category", type(other_exc).__name__),
                "finish_reason": getattr(other_exc, "finish_reason", None),
                "content_present": False,
                "prompt_tokens": getattr(other_exc, "prompt_tokens", None),
                "completion_tokens": getattr(other_exc, "completion_tokens", None),
                "total_tokens": getattr(other_exc, "total_tokens", None),
                "reasoning_tokens": getattr(other_exc, "reasoning_tokens", None),
            }
            attempt_records.append(attempt_record)
            attempt_path, _ = store.persist_raw_provider_attempt(
                query_id=context.query_id,
                attempt_number=attempt_number,
                timestamp_utc=start_time,
                attempt_payload=attempt_record,
            )
            if execution_session is not None:
                execution_session.register_provider_attempt_artifact(
                    attempt_path,
                    attempt_record=attempt_record,
                    collector="harness.answer_execution.provider_boundary",
                )
            if accounting is not None:
                accounting.failed_requests += 1

            # Seal failed raw exchange before raising, preserving pre-parse raw response
            store.persist_raw_provider_exchange(
                query_id=context.query_id,
                timestamp_utc=capture_time,
                provider=transport.provider_name,
                request=exact_request,
                response=raw_response,
                authoritative_attempt_number=attempt_number,
                total_attempts=attempt_number,
                attempts=attempt_records,
                logical_answer_request_id=logical_request_id,
            )
            raise other_exc

    if authoritative_raw_response is None or authoritative_parsed is None or authoritative_attempt_number is None:
        raise AnswerExecutionError("authoritative response missing after attempt loop")

    cumulative_usage = {
        "prompt_tokens": sum(
            r["prompt_tokens"]
            for r in attempt_records
            if r.get("prompt_tokens") is not None
        ),
        "completion_tokens": sum(
            r["completion_tokens"]
            for r in attempt_records
            if r.get("completion_tokens") is not None
        ),
        "total_tokens": sum(
            r["total_tokens"]
            for r in attempt_records
            if r.get("total_tokens") is not None
        ),
        "reasoning_tokens": sum(
            r["reasoning_tokens"]
            for r in attempt_records
            if r.get("reasoning_tokens") is not None
        ),
    }

    provider_path, provider_exchange_sha256 = store.persist_raw_provider_exchange(
        query_id=context.query_id,
        timestamp_utc=capture_time,
        provider=transport.provider_name,
        request=exact_request,
        response=authoritative_raw_response,
        authoritative_attempt_number=authoritative_attempt_number,
        total_attempts=len(attempt_records),
        attempts=attempt_records,
        cumulative_token_usage=cumulative_usage,
        logical_answer_request_id=logical_request_id,
    )
    if execution_session is not None:
        execution_session.register_provider_artifact(
            provider_path,
            transport=transport,
            request=exact_request,
            response=authoritative_raw_response,
            collector="harness.answer_execution.provider_boundary",
        )

    capture = CertifiedAnswerExecutionCapture(
        run_id=store.run_id,
        query_id=context.query_id,
        timestamp_utc=capture_time,
        capture_origin="harness.answer_execution.provider_boundary",
        source_context_contract=context.source_contract,
        context_contract_version=context.schema_version,
        mesa_sha=context.mesa_sha,
        tenant_id=context.tenant_id,
        agent_id=context.agent_id,
        session_id=context.session_id,
        dataset_ids=context.dataset_ids,
        exact_model_visible_context=context.exact_model_visible_context,
        context_evidence_ids=context.context_evidence_ids,
        allowed_retrieval_evidence_ids=context.allowed_retrieval_evidence_ids,
        retrieval_response_sha256=context.retrieval_response_sha256,
        context_candidate_bindings=context.candidate_bindings,
        context_sha256=context_sha256,
        system_prompt=system_prompt,
        system_prompt_sha256=_sha256_bytes(system_prompt.encode("utf-8")),
        question=question,
        question_sha256=_sha256_bytes(question.encode("utf-8")),
        answer_instruction=answer_instruction,
        answer_instruction_sha256=_sha256_bytes(answer_instruction.encode("utf-8")),
        user_prompt=user_prompt,
        user_prompt_sha256=_sha256_bytes(user_prompt.encode("utf-8")),
        provider=transport.provider_name,
        model=model,
        request_parameters=request_parameters,
        exact_provider_request=exact_request,
        request_sha256=request_sha256,
        raw_provider_response=authoritative_raw_response,
        response_sha256=_sha256_bytes(canonical_json_bytes(authoritative_raw_response)),
        provider_exchange_sha256=provider_exchange_sha256,
        parsed_response=authoritative_parsed.model_dump(mode="json"),
    )
    answer_path = store.persist_raw_answer(
        capture,
        execution_id=(execution_session.execution_id if execution_session else None),
    )
    if execution_session is not None:
        if context_raw_path is None:
            raise AnswerExecutionError(
                "official answer capture lacks its trusted MESA context artifact"
            )
        execution_session.register_answer_artifact(
            answer_path,
            provider_raw_path=provider_path,
            context_raw_path=context_raw_path,
        )
    return capture
