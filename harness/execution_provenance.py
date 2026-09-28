"""Process-bound authority for an official qualification execution.

The persisted hashes remain useful integrity checks, but official authority is
additionally tied to an ephemeral session capability held by the canonical
runner.  A manually assembled raw tree therefore cannot be promoted merely by
recomputing SHA sidecars and a manifest.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from typing import Any

from harness.mesa_transport import TrustedMESAResponse, TrustedMESATransport

_SESSION_TOKEN = object()

__all__ = ["ExecutionProvenanceError", "OfficialExecutionSession"]


class ExecutionProvenanceError(RuntimeError):
    """Raised when evidence does not originate in the active official session."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_sidecar(path: Path) -> str:
    sidecar = path.with_suffix(path.suffix + ".SHA256")
    if not path.is_file() or not sidecar.is_file():
        raise ExecutionProvenanceError(f"missing sealed artifact: {path.name}")
    digest = _file_sha256(path)
    parts = sidecar.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[0] != digest or parts[1] != path.name:
        raise ExecutionProvenanceError(f"artifact seal mismatch: {path.name}")
    return digest


class OfficialExecutionSession:
    """Ephemeral capability owned by one canonical runner invocation."""

    schema_version = "mesa.official-execution.v1"

    def __init__(
        self,
        token: object,
        *,
        run_id: str,
        run_dir: Path,
        freeze_sha256: str,
        mesa_sha: str,
        transport: TrustedMESATransport,
        answer_transport: Any | None = None,
    ) -> None:
        if token is not _SESSION_TOKEN:
            raise TypeError("official execution sessions are runner-owned")
        if run_dir.name != run_id:
            raise ExecutionProvenanceError(
                "official run directory basename must equal run_id"
            )
        self.run_id = run_id
        self.run_dir = run_dir
        self.freeze_sha256 = freeze_sha256
        self.mesa_sha = mesa_sha
        self.transport = transport
        self.answer_transport = answer_transport
        self.transport_identity_sha256 = transport.identity_sha256
        answer_transport_identity = (
            getattr(answer_transport, "identity_sha256", None)
            if answer_transport is not None
            else None
        )
        if answer_transport is not None and not isinstance(
            answer_transport_identity, str
        ):
            raise ExecutionProvenanceError(
                "runner-owned answer transport lacks a stable identity"
            )
        self.answer_transport_identity_sha256 = answer_transport_identity
        self._secret = secrets.token_bytes(32)
        nonce = secrets.token_bytes(32)
        self.execution_id = hashlib.sha256(
            _canonical_bytes(
                {
                    "run_id": run_id,
                    "freeze_sha256": freeze_sha256,
                    "mesa_sha": mesa_sha,
                    "transport_identity_sha256": transport.identity_sha256,
                    "answer_transport_identity_sha256": answer_transport_identity,
                    "nonce_sha256": hashlib.sha256(nonce).hexdigest(),
                }
            )
        ).hexdigest()
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self._raw_records: dict[str, dict[str, Any]] = {}
        self._derived_records: dict[str, dict[str, Any]] = {}
        self._capture_started = False
        self._sealed = False

    def _sign(self, payload: Any) -> str:
        return hmac.new(
            self._secret, _canonical_bytes(payload), hashlib.sha256
        ).hexdigest()

    def public_binding(self) -> dict[str, str]:
        binding = {
            "execution_mode": "official",
            "execution_id": self.execution_id,
            "transport_identity_sha256": self.transport_identity_sha256,
            "freeze_sha256": self.freeze_sha256,
        }
        if self.answer_transport_identity_sha256 is not None:
            binding[
                "answer_transport_identity_sha256"
            ] = self.answer_transport_identity_sha256
        return binding

    def write_execution_record(self) -> Path:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            **self.public_binding(),
            "mesa_sha": self.mesa_sha,
            "started_at_utc": self.started_at_utc,
        }
        payload["session_attestation"] = self._sign(payload)
        path = self.run_dir / "official-execution.json"
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != serialized:
            raise ExecutionProvenanceError("official execution record already exists")
        path.write_text(serialized, encoding="utf-8", newline="\n")
        digest = _file_sha256(path)
        path.with_suffix(path.suffix + ".SHA256").write_text(
            f"{digest}  {path.name}\n", encoding="utf-8", newline="\n"
        )
        return path

    def verify_execution_record(self) -> None:
        path = self.run_dir / "official-execution.json"
        _verify_sidecar(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionProvenanceError("invalid official execution record") from exc
        signature = payload.pop("session_attestation", None)
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, self._sign(payload)
        ):
            raise ExecutionProvenanceError("official execution attestation mismatch")
        if (
            payload.get("run_id") != self.run_id
            or payload.get("execution_id") != self.execution_id
        ):
            raise ExecutionProvenanceError("official execution identity mismatch")

    def start_capture(self) -> None:
        if self._capture_started or self._sealed:
            raise ExecutionProvenanceError("official capture lifecycle is invalid")
        for raw_path in sorted((self.run_dir / "raw").rglob("*.json")):
            raise ExecutionProvenanceError(
                f"official raw capture must start empty: {raw_path.relative_to(self.run_dir)}"
            )
        if (self.run_dir / "raw-manifest.json").exists():
            raise ExecutionProvenanceError("official raw manifest pre-exists capture")
        self._capture_started = True

    def _relative_raw_path(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.run_dir.resolve()).as_posix()
        except ValueError as exc:
            raise ExecutionProvenanceError(
                "raw artifact escapes official run directory"
            ) from exc
        if not relative.startswith("raw/"):
            raise ExecutionProvenanceError("official raw artifact is outside raw lanes")
        return relative

    def register_transport_artifact(
        self,
        path: Path,
        *,
        receipt: TrustedMESAResponse,
        request: dict[str, Any],
        response: dict[str, Any],
        collector: str,
    ) -> None:
        if not self._capture_started or self._sealed:
            raise ExecutionProvenanceError(
                "transport capture is outside the official capture window"
            )
        if type(receipt) is not TrustedMESAResponse or not receipt.belongs_to(
            self.transport
        ):
            raise ExecutionProvenanceError(
                "raw response lacks a trusted MESA transport receipt"
            )
        request_sha = hashlib.sha256(_canonical_bytes(request)).hexdigest()
        response_sha = hashlib.sha256(_canonical_bytes(response)).hexdigest()
        if (
            request_sha != receipt.request_sha256
            or response_sha != receipt.response_sha256
        ):
            raise ExecutionProvenanceError(
                "raw request/response differs from trusted transport receipt"
            )
        relative = self._relative_raw_path(path)
        digest = _verify_sidecar(path)
        if relative in self._raw_records:
            raise ExecutionProvenanceError(
                f"duplicate official raw capture: {relative}"
            )
        record = {
            "path": relative,
            "sha256": digest,
            "capture_id": receipt.capture_id,
            "collector": collector,
            "source": "trusted_mesa_transport",
            "endpoint": receipt.endpoint,
            "transport_status": receipt.status_code,
            "request_sha256": request_sha,
            "response_sha256": response_sha,
            **self.public_binding(),
        }
        record["capture_attestation"] = self._sign(record)
        self._raw_records[relative] = record

    def register_state_artifact(
        self, path: Path, *, state_stability_guard: Any, collector: str
    ) -> None:
        if not self._capture_started or self._sealed:
            raise ExecutionProvenanceError(
                "state capture is outside the official capture window"
            )
        from harness.state_proof import PairedStateStabilityGuard

        if type(
            state_stability_guard
        ) is not PairedStateStabilityGuard or not state_stability_guard.is_verified_for(
            self.run_id
        ):
            raise ExecutionProvenanceError(
                "state proof lacks runner-owned paired state stability"
            )
        relative = self._relative_raw_path(path)
        digest = _verify_sidecar(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("run_id") != self.run_id
            or payload.get("execution_id") != self.execution_id
        ):
            raise ExecutionProvenanceError("state proof execution identity mismatch")
        if (
            payload.get("proof_mode") != "stable_state_pair"
            or payload.get("pair_state_stability_verified") is not True
            or payload.get("runtime_quiescence_verified") is not False
        ):
            raise ExecutionProvenanceError(
                "state proof does not verify an honest stable-state pair"
            )
        record = {
            "path": relative,
            "sha256": digest,
            "capture_id": hashlib.sha256(
                _canonical_bytes(
                    {
                        "path": relative,
                        "sha256": digest,
                        "execution_id": self.execution_id,
                    }
                )
            ).hexdigest(),
            "collector": collector,
            "source": "trusted_pair_state_stability",
            "request_sha256": hashlib.sha256(
                _canonical_bytes(state_stability_guard.evidence())
            ).hexdigest(),
            "response_sha256": digest,
            **self.public_binding(),
        }
        record["capture_attestation"] = self._sign(record)
        self._raw_records[relative] = record

    def register_provider_artifact(
        self,
        path: Path,
        *,
        transport: Any,
        request: dict[str, Any],
        response: dict[str, Any],
        collector: str,
    ) -> None:
        if not self._capture_started or self._sealed:
            raise ExecutionProvenanceError(
                "provider capture is outside the official capture window"
            )
        if self.answer_transport is None or transport is not self.answer_transport:
            raise ExecutionProvenanceError(
                "answer artifact lacks the runner-owned provider transport"
            )
        try:
            capture_id = transport.consume_exchange_receipt(request, response)
        except Exception as exc:
            raise ExecutionProvenanceError(
                f"answer provider receipt is invalid: {exc}"
            ) from exc
        relative = self._relative_raw_path(path)
        digest = _verify_sidecar(path)
        request_sha = hashlib.sha256(_canonical_bytes(request)).hexdigest()
        response_sha = hashlib.sha256(_canonical_bytes(response)).hexdigest()
        record = {
            "path": relative,
            "sha256": digest,
            "capture_id": capture_id,
            "collector": collector,
            "source": "trusted_answer_provider_transport",
            "endpoint": "POST /chat/completions",
            "transport_status": 200,
            "request_sha256": request_sha,
            "response_sha256": response_sha,
            **self.public_binding(),
        }
        record["capture_attestation"] = self._sign(record)
        self._raw_records[relative] = record

    def register_answer_artifact(
        self,
        path: Path,
        *,
        provider_raw_path: Path,
        context_raw_path: Path,
    ) -> None:
        if not self._capture_started or self._sealed:
            raise ExecutionProvenanceError(
                "answer capture is outside the official capture window"
            )
        relative = self._relative_raw_path(path)
        provider_relative = self._relative_raw_path(provider_raw_path)
        context_relative = self._relative_raw_path(context_raw_path)
        if (
            provider_relative not in self._raw_records
            or context_relative not in self._raw_records
        ):
            raise ExecutionProvenanceError(
                "answer capture lacks trusted provider/context source evidence"
            )
        digest = _verify_sidecar(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("run_id") != self.run_id
            or payload.get("execution_id") != self.execution_id
        ):
            raise ExecutionProvenanceError("answer capture execution identity mismatch")
        source_rows = [
            {
                "path": source,
                "sha256": self._raw_records[source]["sha256"],
            }
            for source in sorted((provider_relative, context_relative))
        ]
        record = {
            "path": relative,
            "sha256": digest,
            "capture_id": hashlib.sha256(_canonical_bytes(source_rows)).hexdigest(),
            "collector": "harness.answer_execution.execute_answer_and_persist",
            "source": "trusted_answer_capture",
            "request_sha256": hashlib.sha256(_canonical_bytes(source_rows)).hexdigest(),
            "response_sha256": digest,
            "source_raw_paths": [row["path"] for row in source_rows],
            **self.public_binding(),
        }
        record["capture_attestation"] = self._sign(record)
        self._raw_records[relative] = record

    def register_derived_artifact(
        self, path: Path, *, artifact_type: str, source_raw_paths: list[str]
    ) -> None:
        if not self._capture_started or self._sealed:
            raise ExecutionProvenanceError(
                "derived artifact is outside the official capture window"
            )
        try:
            relative = path.resolve().relative_to(self.run_dir.resolve()).as_posix()
        except ValueError as exc:
            raise ExecutionProvenanceError(
                "derived artifact escapes official run directory"
            ) from exc
        digest = _verify_sidecar(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("execution_id") != self.execution_id
            or payload.get("run_id") != self.run_id
        ):
            raise ExecutionProvenanceError(
                "derived artifact execution identity mismatch"
            )
        missing = sorted(set(source_raw_paths) - self._raw_records.keys())
        if missing:
            raise ExecutionProvenanceError(
                f"derived artifact references unregistered official raw evidence: {missing}"
            )
        record = {
            "path": relative,
            "sha256": digest,
            "artifact_type": artifact_type,
            "source_raw_paths": sorted(source_raw_paths),
            **self.public_binding(),
        }
        record["artifact_attestation"] = self._sign(record)
        self._derived_records[relative] = record

    def build_raw_manifest(self, entries: list[dict[str, str]]) -> dict[str, Any]:
        if not self._capture_started:
            raise ExecutionProvenanceError("official capture was not started")
        observed = {entry["path"]: entry["sha256"] for entry in entries}
        registered = {path: row["sha256"] for path, row in self._raw_records.items()}
        if observed != registered:
            missing = sorted(set(observed) - set(registered))
            absent = sorted(set(registered) - set(observed))
            raise ExecutionProvenanceError(
                f"raw tree is not the runner-owned capture set; unregistered={missing}, missing={absent}"
            )
        authoritative_entries = [
            dict(self._raw_records[path]) for path in sorted(self._raw_records)
        ]
        manifest_hash = hashlib.sha256(
            _canonical_bytes(authoritative_entries)
        ).hexdigest()
        payload: dict[str, Any] = {
            "schema_version": "2.0",
            "run_id": self.run_id,
            **self.public_binding(),
            "manifest_hash": manifest_hash,
            "entries": authoritative_entries,
        }
        payload["execution_attestation"] = self._sign(payload)
        self._sealed = True
        return payload

    def verify_raw_manifest(self, manifest: dict[str, Any], expected_hash: str) -> None:
        self.verify_execution_record()
        candidate = dict(manifest)
        signature = candidate.pop("execution_attestation", None)
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, self._sign(candidate)
        ):
            raise ExecutionProvenanceError("raw manifest official attestation mismatch")
        if (
            candidate.get("execution_mode") != "official"
            or candidate.get("execution_id") != self.execution_id
            or candidate.get("run_id") != self.run_id
            or candidate.get("manifest_hash") != expected_hash
        ):
            raise ExecutionProvenanceError("raw manifest official identity mismatch")
        entries = candidate.get("entries")
        if not isinstance(entries, list):
            raise ExecutionProvenanceError("raw manifest entries are invalid")
        if hashlib.sha256(_canonical_bytes(entries)).hexdigest() != expected_hash:
            raise ExecutionProvenanceError(
                "raw manifest hash does not cover authoritative entries"
            )
        for entry in entries:
            row = dict(entry)
            row_signature = row.pop("capture_attestation", None)
            if not isinstance(row_signature, str) or not hmac.compare_digest(
                row_signature, self._sign(row)
            ):
                raise ExecutionProvenanceError("raw capture attestation mismatch")
            path = self.run_dir / str(row.get("path", ""))
            if _verify_sidecar(path) != row.get("sha256"):
                raise ExecutionProvenanceError(
                    "raw capture bytes differ from official manifest"
                )

    def verify_derived_artifact(self, path: Path, artifact_type: str) -> None:
        try:
            relative = path.resolve().relative_to(self.run_dir.resolve()).as_posix()
        except ValueError as exc:
            raise ExecutionProvenanceError(
                "derived artifact escapes official run directory"
            ) from exc
        record = self._derived_records.get(relative)
        if not record or record.get("artifact_type") != artifact_type:
            raise ExecutionProvenanceError(
                f"derived artifact is not registered to official execution: {relative}"
            )
        if record.get("sha256") != _verify_sidecar(path):
            raise ExecutionProvenanceError(
                "derived artifact changed after official registration"
            )
        candidate = dict(record)
        signature = candidate.pop("artifact_attestation", None)
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, self._sign(candidate)
        ):
            raise ExecutionProvenanceError("derived artifact attestation mismatch")


def _begin_official_execution(
    *,
    run_id: str,
    run_dir: Path,
    freeze_sha256: str,
    mesa_sha: str,
    transport: TrustedMESATransport,
    answer_transport: Any | None = None,
) -> OfficialExecutionSession:
    """Create the private ephemeral authority used by the canonical runner."""

    if type(transport) is not TrustedMESATransport:
        raise ExecutionProvenanceError(
            "official execution requires trusted MESA transport"
        )
    if answer_transport is not None:
        from harness.answer_execution import OpenAICompatibleHTTPTransport

        if type(answer_transport) is not OpenAICompatibleHTTPTransport:
            raise ExecutionProvenanceError(
                "official execution requires the runner-owned answer transport"
            )
    return OfficialExecutionSession(
        _SESSION_TOKEN,
        run_id=run_id,
        run_dir=run_dir,
        freeze_sha256=freeze_sha256,
        mesa_sha=mesa_sha,
        transport=transport,
        answer_transport=answer_transport,
    )
