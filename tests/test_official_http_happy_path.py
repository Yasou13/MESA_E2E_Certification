"""Official end-to-end MESA HTTP session lifecycle and scope integration tests."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import http.server
import json
from pathlib import Path
import threading
from typing import Any
import urllib.parse
import urllib.request
import uuid

import pytest

from harness.answer_execution import OpenAICompatibleHTTPTransport
from harness.artifacts import RunArtifactStore
from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.graph_collector import execute_paired_graph_ablation
from harness.identity import IdentityMap
from harness.mesa_adapters import MESAContractIntegrityError
from harness.mesa_transport import (
    MESATransportConfig,
    MESATransportError,
    TrustedMESATransport,
)
from harness.models import EvidenceGroup, GroundTruthItem, RequiredFact
from harness.qualification_runner import (
    QualificationConfig,
    QualificationResult,
    QualificationRunnerError,
    QualificationScope,
    ScopeTestAuthority,
    run_profile_b_qualification,
)
from harness.scope_collector import (
    build_canonical_scope_test_matrix,
    collect_phase7_scope_isolation,
)
from harness.state_proof import establish_paired_state_stability
from tests.scope_fixture_support import frozen_scope_fixture_authority

MESA_SHA = "a" * 40
DATA_SHA = "b" * 40
CERT_SHA = "c" * 40
ROOT = Path(__file__).resolve().parent.parent


class RealisticMESAServer(http.server.ThreadingHTTPServer):
    """Local HTTP test server enforcing MESA V4 session lifecycle and scope contract."""

    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, RealisticMESAHandler)
        self.sessions: dict[str, dict[str, Any]] = {}
        self.ended_sessions: list[str] = []
        self.search_requests: list[dict[str, Any]] = []
        self.context_requests: list[dict[str, Any]] = []


class RealisticMESAHandler(http.server.BaseHTTPRequestHandler):
    server: RealisticMESAServer

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress logging in tests
        pass

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        if path == "/health":
            self._send_json(200, {"status": "healthy"})
            return

        if path == "/v4/capability":
            self._send_json(
                200,
                {
                    "capabilities": {
                        "graph_neighbor_retrieval": True,
                        "vector_retrieval": True,
                        "projection_outbox": True,
                        "idempotent_ingestion": True,
                        "durable_rebuild": True,
                        "graph_projection": True,
                    }
                },
            )
            return

        # Context endpoint: /v4/sessions/{session_id}/context
        if path.startswith("/v4/sessions/") and path.endswith("/context"):
            parts = path.split("/")
            # ["", "v4", "sessions", "{session_id}", "context"]
            session_id = urllib.parse.unquote(parts[3])
            # ENFORCE SESSION VALIDITY
            if session_id not in self.server.sessions:
                self._send_json(404, {"detail": "Unknown session"})
                return

            session = self.server.sessions[session_id]
            self.server.context_requests.append(
                {"session_id": session_id, "path": path}
            )
            ev_id = "ev-rel-1"
            chunk_id = "chunk-rel-1"
            self._send_json(
                200,
                {
                    "session_id": session_id,
                    "tenant_id": session["tenant_id"],
                    "workspace_id": session["workspace_id"],
                    "dataset_ids": session["dataset_ids"],
                    "agent_id": session["agent_id"],
                    "context": "Exact legal fact for qualification answering.",
                    "canonical_memories": [
                        {
                            "assertion_id": ev_id,
                            "evidence_id": ev_id,
                            "chunk_id": chunk_id,
                            "source_chunk_id": chunk_id,
                            "document_id": "doc-1",
                            "content": "Exact legal fact for qualification answering.",
                        }
                    ],
                    "estimated_token_count": 25,
                    "mutations": [],
                },
            )
            return

        # Catalog endpoints for Phase 7 visibility checks
        if path.startswith("/v4/catalog/"):
            self._send_json(
                200, {"items": [], "workspaces": [], "documents": [], "revisions": []}
            )
            return

        self._send_json(404, {"detail": "Not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        body = self._read_json()

        # Session start: POST /v4/sessions/start
        if path == "/v4/sessions/start":
            for field in ("tenant_id", "workspace_id", "dataset_ids", "agent_id"):
                if field not in body:
                    self._send_json(422, {"detail": f"Missing {field}"})
                    return

            session_id = f"sess_native_{uuid.uuid4().hex[:12]}"
            session_record = {
                "session_id": session_id,
                "tenant_id": body["tenant_id"],
                "workspace_id": body["workspace_id"],
                "dataset_ids": list(body["dataset_ids"]),
                "agent_id": body["agent_id"],
                "principal_id": "principal-user-1",
                "status": "ACTIVE",
            }
            self.server.sessions[session_id] = session_record
            self._send_json(201, {"status": "started", **session_record})
            return

        # Session end: POST /v4/sessions/{session_id}/end
        if path.startswith("/v4/sessions/") and path.endswith("/end"):
            parts = path.split("/")
            session_id = urllib.parse.unquote(parts[3])
            if session_id not in self.server.sessions:
                self._send_json(404, {"detail": "Unknown session"})
                return
            self.server.ended_sessions.append(session_id)
            self._send_json(
                200,
                {
                    "status": "ended",
                    "session_id": session_id,
                    "finalization_id": f"fin_{session_id}",
                },
            )
            return

        # Memory search: POST /v4/memory/search
        if path == "/v4/memory/search":
            session_id = body.get("session_id")
            # ENFORCE SESSION VALIDITY
            if not session_id or session_id not in self.server.sessions:
                self._send_json(404, {"detail": "Unknown session"})
                return

            session = self.server.sessions[session_id]
            req_datasets = body.get("dataset_ids") or session["dataset_ids"]

            # ENFORCE DATASET SCOPE
            if not set(req_datasets).issubset(set(session["dataset_ids"])):
                self._send_json(403, {"detail": "Dataset is outside session scope"})
                return

            self.server.search_requests.append(body)
            query = body.get("query", "")
            mode = body.get("graph_mode", "disabled")
            enabled = mode == "enabled"

            # Derive query number if present
            num = 1
            for i in range(1, 11):
                if f"rel-{i}" in query or f"Question {i}" in query:
                    num = i
                    break

            ev_id = f"ev-rel-{num}"
            chunk_id = (
                f"chunk-rel-{num}" if (enabled or num > 2) else f"chunk-unrelated-{num}"
            )

            matched = {
                "assertion_id": ev_id,
                "tenant_id": session["tenant_id"],
                "dataset_id": req_datasets[0],
                "document_id": "doc-1",
                "revision_id": "rev-1",
                "chunk_id": chunk_id,
                "status": "ACTIVE",
                "jurisdiction": "TR",
                "valid_from": "2026-01-01",
                "valid_to": "",
                "evidence_span": "Exact legal fact",
            }

            support = []
            graph_paths = []
            origins = ["vector", "bm25"]
            if enabled:
                origins.append("graph")
                graph_paths.append(
                    {
                        "graph_path_id": f"sha256:path-{num}",
                        "assertion_ids": [f"ev-sup-{num}", ev_id],
                        "entity_ids": ["ent-1", "ent-2", "ent-3"],
                        "edge_directions": ["forward", "reverse"],
                        "predicates": ["governs", "cites"],
                        "seed_id": "ent-1",
                        "score": 0.85,
                    }
                )
                support.append(
                    {
                        "assertion_id": f"ev-sup-{num}",
                        "tenant_id": session["tenant_id"],
                        "dataset_id": req_datasets[0],
                        "document_id": "doc-1",
                        "revision_id": "rev-1",
                        "chunk_id": f"chunk-sup-{num}",
                        "status": "ACTIVE",
                        "jurisdiction": "TR",
                        "valid_from": "2026-01-01",
                        "valid_to": "",
                        "evidence_span": "supporting rule",
                    }
                )

            result = {
                "candidate_id": ev_id,
                "evidence_id": ev_id,
                "assertion_id": ev_id,
                "source_chunk_id": chunk_id,
                "document_id": "doc-1",
                "evidence_span": "Exact legal fact",
                "raw_score": 0.9 if enabled else 0.4,
                "rrf_score": 0.05 if enabled else 0.02,
                "legal_factor": 1.0,
                "final_score": 0.05 if enabled else 0.02,
                "provenance": [matched, *support],
                "matched_assertions": [matched],
                "supporting_assertions": support,
                "retrieval_provenance": {
                    "origins": origins,
                    "lane_ranks": {"vector": 1},
                    "raw_scores": {"vector": 0.9 if enabled else 0.4},
                    "graph_paths": graph_paths,
                },
                "scope_identity": {
                    "tenant_id": session["tenant_id"],
                    "dataset_id": req_datasets[0],
                    "agent_id": session["agent_id"],
                    "jurisdiction": "TR",
                    "status": "ACTIVE",
                },
            }

            self._send_json(
                200,
                {
                    "session_id": session_id,
                    "dataset_ids": req_datasets,
                    "results": [result],
                    "scope_audit": {
                        "contract_version": "mesa.scope-audit.v1",
                        "enforcement_stage": "pre_rank",
                        "requested_scope": {
                            "tenant_id": session["tenant_id"],
                            "agent_id": session["agent_id"],
                            "principal_id": session["principal_id"],
                            "dataset_ids": req_datasets,
                            "jurisdiction": body.get("jurisdiction"),
                            "valid_at": body.get("valid_at"),
                            "valid_from": body.get("valid_from"),
                            "valid_to": body.get("valid_to"),
                        },
                        "requested_scope_identity": "scope-id-live-01",
                        "query_identity": f"query-{hashlib.sha256(query.encode()).hexdigest()[:8]}",
                        "evaluated_candidate_count": 10,
                        "excluded_candidate_count": 8,
                        "eligible_candidate_count": 2,
                        "exclusion_audit_hash": "sha256:" + "0" * 64,
                    },
                    "graph_ablation": {
                        "contract_version": "mesa.graph-ablation.v1",
                        "mode": "enabled" if enabled else "disabled",
                        "pair_identity": "pair-live-01",
                        "query_identity": f"query-{hashlib.sha256(query.encode()).hexdigest()[:8]}",
                        "retrieval_config_identity": "ret-cfg-live-01",
                        "scope_identity": "scope-id-live-01",
                    },
                },
            )
            return

        self._send_json(404, {"detail": "Not found"})


@pytest.fixture
def live_mesa_server():
    server = RealisticMESAServer(("127.0.0.1", 0))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


from tests.test_phase8_9_graph_and_state_proof import (
    _combined_runtime_writer,
    _setup_mock_stores,
)


SYSTEM_PROMPT = "You are a legal assistant."
ANSWER_INSTRUCTION = "Answer strictly based on provided facts."


def _setup_happy_path_repo(
    tmp_path: Path, run_id: str, mesa_base_url: str
) -> tuple[Path, Path, Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    materials: dict[str, list[Path]] = {}

    freeze_dir = tmp_path / "freeze"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    mat_dir = repo / "materials"
    mat_dir.mkdir(parents=True, exist_ok=True)
    for cat in ("config", "prompts", "runtime_identity"):
        p = mat_dir / f"{cat}.txt"
        p.write_text(cat, encoding="utf-8")
        materials[cat] = [p]

    # Exactly 10 relational queries as required by B11
    gt = repo / "ground-truth" / "test.jsonl"
    gt.parent.mkdir(parents=True, exist_ok=True)
    qrels = repo / "ground-truth" / "qrels.jsonl"
    identity = repo / "ground-truth" / "identity-map.jsonl"

    gt_lines = []
    qrel_lines = []
    id_lines = []
    for i in range(1, 11):
        qid = f"Q-REL-{i:02d}"
        src_chunk = f"src-rel-{i}"
        src_sup = f"src-sup-{i}"
        mesa_chunk = f"chunk-rel-{i}"
        gt_lines.append(
            json.dumps(
                {
                    "query_id": qid,
                    "query_class": "RELATIONAL",
                    "question": f"Question {i} rel-{i}?",
                    "expected_source_chunk_ids": [src_chunk, src_sup],
                    "evidence_groups": [
                        {
                            "group_id": f"G{i}-1",
                            "acceptable_source_chunk_ids": [src_chunk],
                        },
                        {
                            "group_id": f"G{i}-2",
                            "acceptable_source_chunk_ids": [src_sup],
                        },
                    ],
                    "required_facts": [
                        {
                            "fact_id": f"F{i}",
                            "claim": "Exact legal fact",
                            "supported_by": [
                                {
                                    "source_chunk_id": src_chunk,
                                    "span_id": f"S{i}",
                                    "exact_text": "Exact legal fact",
                                }
                            ],
                        }
                    ],
                    "acceptable_answer_patterns": [
                        {
                            "mode": "literal",
                            "value": "Exact legal fact",
                            "fact_ids": [f"F{i}"],
                        }
                    ],
                    "forbidden_claims": [],
                    "is_answerable": True,
                },
                ensure_ascii=False,
            )
        )
        qrel_lines.append(
            json.dumps(
                {
                    "query_id": qid,
                    "query_class": "RELATIONAL",
                    "is_answerable": True,
                    "expected_source_chunk_ids": [src_chunk, src_sup],
                    "evidence_groups": [[src_chunk], [src_sup]],
                }
            )
        )
        id_lines.append(
            json.dumps(
                {
                    "mesa_chunk_id": mesa_chunk,
                    "source_chunk_id": src_chunk,
                    "content_hash": "1" * 64,
                    "delivery_state": "COMMITTED",
                    "document_id": "doc-1",
                    "remote_mutation_id": f"mutation-{i}",
                    "version_id": "revision-1",
                }
            )
        )
        # Also add support and unrelated chunks to identity map
        id_lines.append(
            json.dumps(
                {
                    "mesa_chunk_id": f"chunk-sup-{i}",
                    "source_chunk_id": f"src-sup-{i}",
                    "content_hash": "2" * 64,
                    "delivery_state": "COMMITTED",
                    "document_id": "doc-1",
                    "remote_mutation_id": f"mutation-sup-{i}",
                    "version_id": "revision-1",
                }
            )
        )
        id_lines.append(
            json.dumps(
                {
                    "mesa_chunk_id": f"chunk-unrelated-{i}",
                    "source_chunk_id": f"src-unrelated-{i}",
                    "content_hash": "3" * 64,
                    "delivery_state": "COMMITTED",
                    "document_id": "doc-1",
                    "remote_mutation_id": f"mutation-unrelated-{i}",
                    "version_id": "revision-1",
                }
            )
        )

    gt.write_text("\n".join(gt_lines) + "\n", encoding="utf-8")
    materials["ground_truth"] = [gt]

    qrels.write_text("\n".join(qrel_lines) + "\n", encoding="utf-8")
    materials["qrels"] = [qrels]

    scope_authority, scope_identity_rows = frozen_scope_fixture_authority()
    id_lines.extend(json.dumps(row) for row in scope_identity_rows)
    identity.write_text("\n".join(id_lines) + "\n", encoding="utf-8")
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
            "answer_authority": {
                "provider": "openai_compatible",
                "model": "openai/gpt-oss-20b",
                "system_prompt_sha256": hashlib.sha256(
                    SYSTEM_PROMPT.encode("utf-8")
                ).hexdigest(),
                "answer_instruction_sha256": hashlib.sha256(
                    ANSWER_INSTRUCTION.encode("utf-8")
                ).hexdigest(),
                "request_parameters_sha256": hashlib.sha256(b"{}").hexdigest(),
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
            "mesa_transport": {
                "base_url": mesa_base_url,
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


class _MockAnswerResponse:
    def __init__(self) -> None:
        self._raw = json.dumps(
            {
                "id": "chatcmpl-live",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "answer": "Exact legal fact is established under law.",
                                    "evidence_chunk_ids": ["chunk-rel-1"],
                                    "insufficient_evidence": False,
                                    "claims": [],
                                }
                            ),
                        }
                    }
                ],
                "model": "openai/gpt-oss-20b",
            }
        ).encode("utf-8")

    def __enter__(self) -> "_MockAnswerResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def read(self) -> bytes:
        return self._raw


def test_official_runner_http_happy_path(
    tmp_path: Path,
    live_mesa_server: tuple[str, RealisticMESAServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mandatory verification: complete official qualification HTTP flow over real sockets."""
    base_url, server = live_mesa_server
    run_id = "RUN-OFFICIAL-HTTP-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    # Intercept answer provider https://provider.invalid calls only; all MESA calls go to real TCP socket
    orig_urlopen = urllib.request.urlopen

    def selective_urlopen(req: Any, timeout: float | None = None) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "provider.invalid" in url:
            return _MockAnswerResponse()
        return orig_urlopen(req, timeout=timeout)

    monkeypatch.setattr(urllib.request, "urlopen", selective_urlopen)

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        answer_provider_base_url="https://provider.invalid/v1",
        answer_provider_api_key="secret-provider-key",
        answer_system_prompt=SYSTEM_PROMPT,
        answer_instruction=ANSWER_INSTRUCTION,
        answer_request_parameters={},
    )

    with _combined_runtime_writer(sql.parent):
        result = run_profile_b_qualification(config)

    # 1. Official runner must complete without error
    assert result.status == "COMPLETED"
    assert result.run_id == run_id

    # 2. Server must have created a real native session
    assert len(server.sessions) == 1
    native_session_id = next(iter(server.sessions.keys()))
    assert native_session_id.startswith("sess_native_")

    # 3. All retrieval requests must have used the native session ID (zero synthetic IDs)
    assert len(server.search_requests) > 0
    for req in server.search_requests:
        assert req["session_id"] == native_session_id
        assert not req["session_id"].startswith("session-")

    # 4. Context requests must have used the native session ID
    assert len(server.context_requests) > 0
    for req in server.context_requests:
        assert req["session_id"] == native_session_id

    # 5. Session was properly cleaned up via end_session
    assert native_session_id in server.ended_sessions

    # 6. Authoritative session bootstrap artifact is sealed in raw-manifest
    bootstrap_file = run_dir / "raw" / "sessions" / "qualification.json"
    assert bootstrap_file.is_file()
    assert bootstrap_file.with_suffix(".json.SHA256").is_file()
    bootstrap_payload = json.loads(bootstrap_file.read_text(encoding="utf-8"))
    assert bootstrap_payload["native_session_id"] == native_session_id
    assert bootstrap_payload["lane"] == "sessions"
    assert bootstrap_payload["purpose"] == "qualification"

    manifest_file = run_dir / "raw-manifest.json"
    assert manifest_file.is_file()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    raw_paths = [e["path"] for e in manifest_data["entries"]]
    assert "raw/sessions/qualification.json" in raw_paths

    # 7. Phase 7 scope isolation artifact binds native session
    scope_file = run_dir / "scope-isolation.json"
    assert scope_file.is_file()
    scope_data = json.loads(scope_file.read_text(encoding="utf-8"))
    assert scope_data["session_id"] == native_session_id

    # 8. Graph ablation artifact binds native session
    graph_file = run_dir / "graph-ablation.json"
    assert graph_file.is_file()
    graph_data = json.loads(graph_file.read_text(encoding="utf-8"))
    assert graph_data["session_id"] == native_session_id


def test_server_enforces_rejection_of_unknown_session_before_start(
    live_mesa_server: tuple[str, RealisticMESAServer],
) -> None:
    """Proves server returns 404 for unknown session in POST /v4/memory/search."""
    base_url, _ = live_mesa_server
    transport = TrustedMESATransport(
        MESATransportConfig(
            base_url=base_url,
            api_key="secret-key",
            timeout_seconds=5.0,
            api_version="v4",
            expected_mesa_sha=MESA_SHA,
            runtime_profile="combined",
        )
    )

    with pytest.raises(MESATransportError, match="HTTP 404"):
        transport.search(
            {
                "session_id": "session-unknown-001",
                "dataset_ids": ["dataset-legal-1"],
                "query": "pre-session search test",
                "limit": 5,
            }
        )


def test_server_enforces_rejection_of_unknown_session_in_context(
    live_mesa_server: tuple[str, RealisticMESAServer],
) -> None:
    """Proves server returns 404 for unknown session in GET /v4/sessions/{session_id}/context."""
    base_url, _ = live_mesa_server
    transport = TrustedMESATransport(
        MESATransportConfig(
            base_url=base_url,
            api_key="secret-key",
            timeout_seconds=5.0,
            api_version="v4",
            expected_mesa_sha=MESA_SHA,
            runtime_profile="combined",
        )
    )

    with pytest.raises(MESATransportError, match="HTTP 404"):
        transport.call_endpoint(
            "GET /v4/sessions/{session_id}/context",
            {"session_id": "session-unknown-002", "token_budget": 2048},
        )


def test_server_enforces_dataset_scoping(
    live_mesa_server: tuple[str, RealisticMESAServer],
) -> None:
    """Proves server returns 403 when search requests dataset outside session scope."""
    base_url, _ = live_mesa_server
    transport = TrustedMESATransport(
        MESATransportConfig(
            base_url=base_url,
            api_key="secret-key",
            timeout_seconds=5.0,
            api_version="v4",
            expected_mesa_sha=MESA_SHA,
            runtime_profile="combined",
        )
    )
    receipt = transport.start_session(
        {
            "tenant_id": "tenant-auth",
            "workspace_id": "workspace-auth",
            "dataset_ids": ["dataset-legal-1"],
            "agent_id": "agent-auth",
        }
    )
    sess_id = receipt.payload["session_id"]

    with pytest.raises(MESATransportError, match="HTTP 403"):
        transport.search(
            {
                "session_id": sess_id,
                "dataset_ids": ["dataset-outside-scope"],
                "query": "out of scope test",
                "limit": 5,
            }
        )


def test_runner_fails_closed_when_caller_attempts_to_override_frozen_scope(
    tmp_path: Path, live_mesa_server: tuple[str, RealisticMESAServer]
) -> None:
    """Proves runner rejects caller scope that contradicts frozen authority."""
    base_url, _ = live_mesa_server
    run_id = "RUN-SCOPE-OVERRIDE-FAIL"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    contradictory_scope = QualificationScope(
        tenant_id="tenant-caller-override",
        workspace_id="workspace-auth",
        dataset_ids=["dataset-legal-1"],
        agent_id="agent-auth",
        expected_principal="principal-user-1",
    )

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        qualification_scope=contradictory_scope,
    )

    with pytest.raises(
        QualificationRunnerError,
        match="caller-provided qualification_scope contradicts frozen qualification authority",
    ):
        run_profile_b_qualification(config)


def test_runner_fails_closed_when_session_created_under_wrong_tenant(
    tmp_path: Path,
    live_mesa_server: tuple[str, RealisticMESAServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves runner validates session response scope against requested frozen scope."""
    base_url, server = live_mesa_server
    run_id = "RUN-WRONG-TENANT-FAIL"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    # Monkeypatch transport.start_session to return wrong tenant in session response
    orig_start = TrustedMESATransport.start_session

    def bad_start(self: Any, payload: dict[str, Any]) -> Any:
        receipt = orig_start(self, payload)
        bad_payload = dict(receipt.payload)
        bad_payload["tenant_id"] = "wrong-tenant-injected"
        object.__setattr__(receipt, "payload", bad_payload)
        return receipt

    monkeypatch.setattr(TrustedMESATransport, "start_session", bad_start)

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        answer_provider_base_url="https://provider.invalid/v1",
        answer_provider_api_key="secret-provider-key",
        answer_system_prompt=SYSTEM_PROMPT,
        answer_instruction=ANSWER_INSTRUCTION,
        answer_request_parameters={},
    )

    with pytest.raises(
        QualificationRunnerError,
        match="session bootstrap tenant mismatch",
    ):
        run_profile_b_qualification(config)


def test_graph_ablation_fails_closed_on_session_mismatch(
    tmp_path: Path,
) -> None:
    """Proves execute_paired_graph_ablation rejects mismatched or synthetic sessions."""
    run_id = "RUN-GRAPH-SESSION-FAIL"
    run_dir = tmp_path / run_id
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir(parents=True, exist_ok=True)
    sql, lance, kuzu = _setup_mock_stores(stores_dir)

    rel_queries = [
        GroundTruthItem(
            query_id=f"Q-REL-{i}",
            question=f"Q {i}",
            expected_source_chunk_ids=[f"src-{i}"],
            evidence_groups=[
                EvidenceGroup(group_id="G1", acceptable_source_chunk_ids=[f"src-{i}"])
            ],
            required_facts=[RequiredFact(fact_id="F1", claim="c")],
            query_class="RELATIONAL",
            is_answerable=True,
        )
        for i in range(1, 11)
    ]
    id_map = IdentityMap()
    for i in range(1, 11):
        id_map.add_mapping(f"chunk-rel-{i}", f"src-{i}")

    def bad_executor(mode: str, req: dict) -> dict:
        # Return a response with a different session_id than requested
        return {
            "session_id": "different-session-id",
            "dataset_ids": req.get("dataset_ids", ["dataset-legal-1"]),
            "results": [],
            "graph_ablation": {
                "contract_version": "mesa.graph-ablation.v1",
                "mode": mode,
                "pair_identity": "pair-01",
                "query_identity": "q-01",
                "retrieval_config_identity": "cfg-01",
                "scope_identity": "scope-01",
            },
        }

    with pytest.raises(MESAContractIntegrityError, match="session_id mismatch"):
        execute_paired_graph_ablation(
            run_id=run_id,
            run_dir=run_dir,
            mesa_sha=MESA_SHA,
            rel_queries=rel_queries,
            identity_map=id_map,
            sqlite_path=sql,
            lancedb_dir=lance,
            kuzu_dir=kuzu,
            mesa_executor=bad_executor,
            session_id="expected-native-session",
        )


def test_runner_fails_closed_when_session_created_under_wrong_dataset(
    tmp_path: Path,
    live_mesa_server: tuple[str, RealisticMESAServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves runner fails closed if session response contains wrong dataset_ids."""
    base_url, _ = live_mesa_server
    run_id = "RUN-WRONG-DATASET-FAIL"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    orig_start = TrustedMESATransport.start_session

    def bad_start(self: Any, payload: dict[str, Any]) -> Any:
        receipt = orig_start(self, payload)
        bad_payload = dict(receipt.payload)
        bad_payload["dataset_ids"] = ["dataset-unauthorized"]
        object.__setattr__(receipt, "payload", bad_payload)
        return receipt

    monkeypatch.setattr(TrustedMESATransport, "start_session", bad_start)

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        answer_provider_base_url="https://provider.invalid/v1",
        answer_provider_api_key="secret-provider-key",
        answer_system_prompt=SYSTEM_PROMPT,
        answer_instruction=ANSWER_INSTRUCTION,
        answer_request_parameters={},
    )

    with pytest.raises(
        QualificationRunnerError,
        match="session bootstrap datasets mismatch",
    ):
        run_profile_b_qualification(config)


def test_runner_fails_closed_when_session_created_under_wrong_agent(
    tmp_path: Path,
    live_mesa_server: tuple[str, RealisticMESAServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves runner fails closed if session response contains wrong agent_id."""
    base_url, _ = live_mesa_server
    run_id = "RUN-WRONG-AGENT-FAIL"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    orig_start = TrustedMESATransport.start_session

    def bad_start(self: Any, payload: dict[str, Any]) -> Any:
        receipt = orig_start(self, payload)
        bad_payload = dict(receipt.payload)
        bad_payload["agent_id"] = "agent-rogue"
        object.__setattr__(receipt, "payload", bad_payload)
        return receipt

    monkeypatch.setattr(TrustedMESATransport, "start_session", bad_start)

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        answer_provider_base_url="https://provider.invalid/v1",
        answer_provider_api_key="secret-provider-key",
        answer_system_prompt=SYSTEM_PROMPT,
        answer_instruction=ANSWER_INSTRUCTION,
        answer_request_parameters={},
    )

    with pytest.raises(
        QualificationRunnerError,
        match="session bootstrap agent mismatch",
    ):
        run_profile_b_qualification(config)


def test_runner_fails_closed_when_session_response_missing_session_id(
    tmp_path: Path,
    live_mesa_server: tuple[str, RealisticMESAServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves runner fails closed if session response does not contain session_id."""
    base_url, _ = live_mesa_server
    run_id = "RUN-NO-SESSION-ID-FAIL"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    orig_start = TrustedMESATransport.start_session

    def bad_start(self: Any, payload: dict[str, Any]) -> Any:
        receipt = orig_start(self, payload)
        bad_payload = dict(receipt.payload)
        bad_payload.pop("session_id", None)
        object.__setattr__(receipt, "payload", bad_payload)
        return receipt

    monkeypatch.setattr(TrustedMESATransport, "start_session", bad_start)

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        answer_provider_base_url="https://provider.invalid/v1",
        answer_provider_api_key="secret-provider-key",
        answer_system_prompt=SYSTEM_PROMPT,
        answer_instruction=ANSWER_INSTRUCTION,
        answer_request_parameters={},
    )

    with pytest.raises(
        QualificationRunnerError,
        match="native MESA session bootstrap response missing session_id",
    ):
        run_profile_b_qualification(config)


def test_runner_fails_closed_when_frozen_scope_missing(
    tmp_path: Path, live_mesa_server: tuple[str, RealisticMESAServer]
) -> None:
    """Proves runner fails closed when freeze lacks qualification_scope."""
    base_url, _ = live_mesa_server
    run_id = "RUN-NO-SCOPE-FAIL"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    freeze = json.loads(fp.read_text(encoding="utf-8"))
    freeze["runtime_identities"].pop("qualification_scope", None)
    fp.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(fp.read_bytes()).hexdigest()
    cp.write_text(f"{digest}  {fp.name}\n", encoding="utf-8")

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        answer_provider_base_url="https://provider.invalid/v1",
        answer_provider_api_key="secret-provider-key",
        answer_system_prompt=SYSTEM_PROMPT,
        answer_instruction=ANSWER_INSTRUCTION,
        answer_request_parameters={},
    )

    with pytest.raises(
        QualificationRunnerError,
        match=r"frozen qualification scope authority.*is missing",
    ):
        run_profile_b_qualification(config)


def test_runner_fails_closed_when_frozen_scope_test_authority_missing(
    tmp_path: Path, live_mesa_server: tuple[str, RealisticMESAServer]
) -> None:
    """Proves runner fails closed when freeze lacks scope_test_authority."""
    base_url, _ = live_mesa_server
    run_id = "RUN-NO-SCOPE-AUTH-FAIL"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo, fp, cp, sql, lance, kuzu = _setup_happy_path_repo(
        tmp_path, run_id=run_id, mesa_base_url=base_url
    )

    freeze = json.loads(fp.read_text(encoding="utf-8"))
    freeze["runtime_identities"].pop("scope_test_authority", None)
    fp.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(fp.read_bytes()).hexdigest()
    cp.write_text(f"{digest}  {fp.name}\n", encoding="utf-8")

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
        mesa_base_url=base_url,
        mesa_api_key="secret-qualification-key",
        answer_provider_base_url="https://provider.invalid/v1",
        answer_provider_api_key="secret-provider-key",
        answer_system_prompt=SYSTEM_PROMPT,
        answer_instruction=ANSWER_INSTRUCTION,
        answer_request_parameters={},
    )

    with pytest.raises(
        QualificationRunnerError,
        match=r"frozen scope test authority.*is missing",
    ):
        run_profile_b_qualification(config)


def test_fake_session_bootstrap_fails_manifest_validation(tmp_path: Path) -> None:
    """Proves fake session bootstrap injected into raw tree is rejected during sealing."""
    from harness.artifacts import RunArtifactStore
    from harness.execution_provenance import _begin_official_execution
    from harness.mesa_transport import MESATransportConfig, TrustedMESATransport

    run_id = "RUN-FAKE-BOOTSTRAP"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    store = RunArtifactStore(run_dir=run_dir, run_id=run_id)
    store.initialize()

    transport = TrustedMESATransport(
        MESATransportConfig(
            base_url="http://127.0.0.1:1",
            api_key="key",
            timeout_seconds=5.0,
            api_version="v4",
            expected_mesa_sha="0" * 40,
            runtime_profile="combined",
        )
    )
    session = _begin_official_execution(
        run_id=run_id,
        run_dir=run_dir,
        freeze_sha256="0" * 64,
        mesa_sha="0" * 40,
        transport=transport,
    )
    session.start_capture()

    # Manually fabricate a raw session bootstrap file after capture has started
    fake_path = store.raw_sessions_dir / "qualification.json"
    fake_payload = {
        "run_id": run_id,
        "lane": "session_bootstrap",
        "purpose": "qualification",
        "session_id": "sess_injected_fake",
    }
    fake_bytes = json.dumps(fake_payload).encode("utf-8")
    fake_path.write_bytes(fake_bytes)
    (store.raw_sessions_dir / "qualification.json.SHA256").write_text(
        f"{hashlib.sha256(fake_bytes).hexdigest()}  qualification.json\n",
        encoding="utf-8",
    )

    # compute_raw_manifest with an official session that didn't register this fake file must fail closed
    with pytest.raises(Exception, match="unregistered"):
        store.compute_raw_manifest(execution_session=session)
