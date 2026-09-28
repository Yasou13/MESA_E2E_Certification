"""Runner-owned HTTP transport for official MESA qualification requests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

_RECEIPT_TOKEN = object()
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class MESATransportError(RuntimeError):
    """Raised when the trusted MESA HTTP boundary cannot be verified."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class MESATransportConfig:
    base_url: str
    api_key: str
    timeout_seconds: float
    api_version: str
    expected_mesa_sha: str
    runtime_profile: str


class TrustedMESAResponse:
    """Response receipt minted only after the runner-owned HTTP call completes."""

    __slots__ = (
        "payload",
        "status_code",
        "latency_ms",
        "endpoint",
        "request_sha256",
        "response_sha256",
        "capture_id",
        "_transport_marker",
    )

    def __init__(
        self,
        token: object,
        *,
        payload: dict[str, Any],
        status_code: int,
        latency_ms: float,
        endpoint: str,
        request_sha256: str,
        response_sha256: str,
        capture_id: str,
        transport_marker: object,
    ) -> None:
        if token is not _RECEIPT_TOKEN:
            raise TypeError("trusted MESA response receipts are transport-owned")
        self.payload = payload
        self.status_code = status_code
        self.latency_ms = latency_ms
        self.endpoint = endpoint
        self.request_sha256 = request_sha256
        self.response_sha256 = response_sha256
        self.capture_id = capture_id
        self._transport_marker = transport_marker

    def belongs_to(self, transport: "TrustedMESATransport") -> bool:
        return self._transport_marker is transport._marker


class TrustedMESATransport:
    """Bounded JSON transport constructed only by the official runner.

    The object accepts configuration, never caller-provided execution callbacks.
    Every successful exchange returns an instance-bound receipt which is consumed
    by the official execution provenance session.
    """

    implementation_id = "harness.mesa_transport.urllib-json.v1"

    def __init__(self, config: MESATransportConfig) -> None:
        parsed = urllib.parse.urlsplit(config.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MESATransportError("MESA base URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise MESATransportError(
                "MESA base URL must not contain credentials, query, or fragment"
            )
        if not config.api_key:
            raise MESATransportError("MESA API key is required")
        if config.timeout_seconds <= 0:
            raise MESATransportError("MESA timeout must be positive")
        if config.api_version != "v4":
            raise MESATransportError("official qualification requires MESA API v4")
        if config.runtime_profile != "combined":
            raise MESATransportError(
                "official qualification requires the graph-capable combined runtime profile"
            )
        if len(config.expected_mesa_sha) not in {40, 64}:
            raise MESATransportError("expected MESA SHA must be a full Git SHA")
        self._base_url = config.base_url.rstrip("/")
        self._api_key = config.api_key
        self._timeout = float(config.timeout_seconds)
        self._api_version = config.api_version
        self._expected_mesa_sha = config.expected_mesa_sha
        self._runtime_profile = config.runtime_profile
        self._marker = object()
        identity_payload = {
            "implementation": self.implementation_id,
            "base_url": self._base_url,
            "api_version": self._api_version,
            "expected_mesa_sha": self._expected_mesa_sha,
            "runtime_profile": self._runtime_profile,
        }
        self.identity_sha256 = hashlib.sha256(
            _canonical_bytes(identity_payload)
        ).hexdigest()

    @property
    def base_url(self) -> str:
        return self._base_url

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        receipt_payload: dict[str, Any] | None = None,
    ) -> TrustedMESAResponse:
        if method not in {"GET", "POST"}:
            raise MESATransportError(f"unsupported MESA method: {method}")
        if (
            not path.startswith("/")
            or "://" in path
            or "#" in path
            or "?" in path
            or "{" in path
            or "}" in path
        ):
            raise MESATransportError("MESA endpoint path is unsafe")
        request_payload = dict(payload or {})
        captured_request = dict(
            receipt_payload if receipt_payload is not None else request_payload
        )
        url = self._base_url + path
        data: bytes | None = None
        headers = {"Accept": "application/json", "X-API-Key": self._api_key}
        if method == "GET":
            if request_payload:
                url += "?" + urllib.parse.urlencode(request_payload, doseq=True)
        else:
            data = _canonical_bytes(request_payload)
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status = int(response.status)
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            code_suffix = (
                f" HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else ""
            )
            raise MESATransportError(
                f"MESA request failed for {method} {path}{code_suffix}: {type(exc).__name__}"
            ) from exc
        latency_ms = (time.monotonic() - started) * 1000.0
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise MESATransportError("MESA response exceeded the capture limit")
        if not 200 <= status < 300:
            raise MESATransportError(f"MESA returned HTTP {status} for {method} {path}")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MESATransportError("MESA returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise MESATransportError("MESA response must be a JSON object")
        request_sha = hashlib.sha256(_canonical_bytes(captured_request)).hexdigest()
        response_sha = hashlib.sha256(_canonical_bytes(decoded)).hexdigest()
        capture_id = hashlib.sha256(
            _canonical_bytes(
                {
                    "endpoint": f"{method} {path}",
                    "request_sha256": request_sha,
                    "response_sha256": response_sha,
                    "status_code": status,
                    "transport_identity_sha256": self.identity_sha256,
                }
            )
        ).hexdigest()
        return TrustedMESAResponse(
            _RECEIPT_TOKEN,
            payload=decoded,
            status_code=status,
            latency_ms=latency_ms,
            endpoint=f"{method} {path}",
            request_sha256=request_sha,
            response_sha256=response_sha,
            capture_id=capture_id,
            transport_marker=self._marker,
        )

    def call_endpoint(
        self, endpoint: str, payload: dict[str, Any]
    ) -> TrustedMESAResponse:
        try:
            method, path = endpoint.split(" ", 1)
        except ValueError as exc:
            raise MESATransportError(
                f"invalid MESA endpoint contract: {endpoint!r}"
            ) from exc
        wire_payload = dict(payload)
        if "{session_id}" in path:
            session_id = wire_payload.pop("session_id", None)
            if not isinstance(session_id, str) or not session_id:
                raise MESATransportError(
                    "MESA session context endpoint requires session_id"
                )
            path = path.replace("{session_id}", urllib.parse.quote(session_id, safe=""))
        return self._request(
            method,
            path,
            wire_payload,
            receipt_payload=payload,
        )

    def search(self, payload: dict[str, Any]) -> TrustedMESAResponse:
        return self._request("POST", "/v4/memory/search", payload)

    def start_session(self, payload: dict[str, Any]) -> TrustedMESAResponse:
        return self._request("POST", "/v4/sessions/start", payload)

    def end_session(self, session_id: str) -> TrustedMESAResponse:
        if not isinstance(session_id, str) or not session_id:
            raise MESATransportError("MESA session end requires session_id")
        path = f"/v4/sessions/{urllib.parse.quote(session_id, safe='')}/end"
        return self._request("POST", path, {"session_id": session_id})

    def preflight(self) -> TrustedMESAResponse:
        receipt = self._request("GET", "/health", None)
        if receipt.payload.get("status") not in {"healthy", "ready"}:
            raise MESATransportError(
                f"MESA health preflight is not healthy: {receipt.payload.get('status')!r}"
            )
        capability = self._request("GET", "/v4/capability", None)
        capabilities = capability.payload.get("capabilities")
        if (
            not isinstance(capabilities, dict)
            or capabilities.get("graph_neighbor_retrieval") is not True
        ):
            raise MESATransportError(
                "MESA capability preflight lacks native graph retrieval"
            )
        return receipt
