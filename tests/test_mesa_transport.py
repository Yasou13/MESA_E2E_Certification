"""Focused contract tests for the runner-owned MESA HTTP transport."""

from __future__ import annotations

import json
import hashlib
import urllib.request

import pytest

from harness.mesa_transport import (
    MESATransportConfig,
    MESATransportError,
    TrustedMESATransport,
)

MESA_SHA = "a" * 40


class _Response:
    status = 200

    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._raw


def _transport() -> TrustedMESATransport:
    return TrustedMESATransport(
        MESATransportConfig(
            base_url="https://mesa.internal",
            api_key="secret-test-key",
            timeout_seconds=5.0,
            api_version="v4",
            expected_mesa_sha=MESA_SHA,
            runtime_profile="combined",
        )
    )


def test_transport_performs_http_and_mints_instance_bound_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, *, timeout: float) -> _Response:
        observed.update(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "api_key": request.get_header("X-api-key"),
                "content_type": request.get_header("Content-type"),
                "body": request.data,
                "timeout": timeout,
            }
        )
        return _Response({"results": [], "scope_audit": {}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = _transport()
    request_payload = {"query": "trusted request", "limit": 5}

    receipt = transport.search(request_payload)

    assert observed == {
        "url": "https://mesa.internal/v4/memory/search",
        "method": "POST",
        "api_key": "secret-test-key",
        "content_type": "application/json",
        "body": b'{"limit":5,"query":"trusted request"}',
        "timeout": 5.0,
    }
    assert receipt.payload == {"results": [], "scope_audit": {}}
    assert receipt.endpoint == "POST /v4/memory/search"
    assert receipt.belongs_to(transport) is True
    assert receipt.belongs_to(_transport()) is False


def test_transport_resolves_session_path_without_leaking_path_parameter_to_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, *, timeout: float) -> _Response:
        observed["url"] = request.full_url
        return _Response({"session_id": "session/with space", "context": ""})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = _transport()
    payload = {"session_id": "session/with space", "token_budget": 2048}

    receipt = transport.call_endpoint("GET /v4/sessions/{session_id}/context", payload)

    assert observed["url"] == (
        "https://mesa.internal/v4/sessions/session%2Fwith%20space/context"
        "?token_budget=2048"
    )
    expected_request = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert receipt.request_sha256 == hashlib.sha256(expected_request).hexdigest()


def test_preflight_requires_live_native_graph_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: urllib.request.Request, *, timeout: float) -> _Response:
        if request.full_url.endswith("/health"):
            return _Response({"status": "healthy"})
        return _Response({"capabilities": {"graph_neighbor_retrieval": False}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(MESATransportError, match="native graph retrieval"):
        _transport().preflight()


def test_transport_rejects_non_production_runtime_profile() -> None:
    with pytest.raises(MESATransportError, match="graph-capable combined"):
        TrustedMESATransport(
            MESATransportConfig(
                base_url="https://mesa.internal",
                api_key="secret-test-key",
                timeout_seconds=5.0,
                api_version="v4",
                expected_mesa_sha=MESA_SHA,
                runtime_profile="test-isolated",
            )
        )


@pytest.mark.parametrize(
    ("base_url", "api_key", "message"),
    [
        ("file:///tmp/fake-mesa", "key", "absolute HTTP"),
        ("https://mesa.internal?override=1", "key", "must not contain"),
        ("https://mesa.internal", "", "API key is required"),
    ],
)
def test_transport_rejects_untrusted_configuration(
    base_url: str, api_key: str, message: str
) -> None:
    with pytest.raises(MESATransportError, match=message):
        TrustedMESATransport(
            MESATransportConfig(
                base_url=base_url,
                api_key=api_key,
                timeout_seconds=5.0,
                api_version="v4",
                expected_mesa_sha=MESA_SHA,
                runtime_profile="combined",
            )
        )
