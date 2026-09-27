"""Exact OpenAI-compatible answer execution and raw-first capture."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
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
    pass


class ProviderTransport(Protocol):
    provider_name: str

    def complete(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenAICompatibleHTTPTransport:
    """Minimal production transport with bounded timeout and no SDK retries."""

    provider_name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: float):
        if not base_url.startswith("https://"):
            raise ValueError("provider base_url must use HTTPS")
        if not api_key:
            raise ValueError("provider API key is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._timeout = float(timeout_seconds)

    def complete(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        body = canonical_json_bytes(request_payload)
        request = urllib.request.Request(
            self._url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise AnswerExecutionError(
                f"provider request failed: {type(exc).__name__}"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AnswerExecutionError("provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AnswerExecutionError("provider response must be a JSON object")
        return payload


def _parse_openai_compatible_response(raw_response: dict[str, Any]) -> AnswerResponse:
    try:
        choices = raw_response["choices"]
        content = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AnswerExecutionError(
            "provider response lacks choices[0].message.content"
        ) from exc
    if not isinstance(content, str):
        raise AnswerExecutionError("provider message content must be a string")
    try:
        return AnswerResponse.model_validate_json(content)
    except Exception as exc:
        raise AnswerExecutionError(
            "provider answer does not satisfy AnswerResponse"
        ) from exc


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
) -> CertifiedAnswerExecutionCapture:
    """Call the provider once and seal the exact boundary capture before scoring."""

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
    raw_response = transport.complete(exact_request)
    capture_time = timestamp_utc or datetime.now(timezone.utc)
    _, provider_exchange_sha256 = store.persist_raw_provider_exchange(
        query_id=context.query_id,
        timestamp_utc=capture_time,
        provider=transport.provider_name,
        request=exact_request,
        response=raw_response,
    )
    parsed = _parse_openai_compatible_response(raw_response)
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
        context_sha256=_sha256_bytes(
            context.exact_model_visible_context.encode("utf-8")
        ),
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
        request_sha256=_sha256_bytes(canonical_json_bytes(exact_request)),
        raw_provider_response=raw_response,
        response_sha256=_sha256_bytes(canonical_json_bytes(raw_response)),
        provider_exchange_sha256=provider_exchange_sha256,
        parsed_response=parsed.model_dump(mode="json"),
    )
    store.persist_raw_answer(capture)
    return capture
