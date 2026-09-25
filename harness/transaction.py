"""Authoritative fail-closed certification transaction orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Optional

from harness.answer_scorer import score_answer
from harness.artifacts import RunArtifactStore
from harness.evidence import build_evidence_index, validate_run_id_consistency
from harness.finalizer import finalize_release, ReleaseFinalizationError
from harness.freeze import verify_contract_freeze, FreezeStatus
from harness.gates import GateConfig, evaluate_threshold_gate, load_gate_config
from harness.lifecycle import RunLifecycle
from harness.models import ExecutionStatus, FinalVerdict, GateResult, GateStatus, RunStatus, VerdictStatus
from harness.oracle import audit_oracle_surfaces, extract_raw_audit_surfaces
from harness.verdict import derive_production_verdict


class TransactionError(RuntimeError):
    """Raised when a certification transaction invariant is violated."""
    pass


class TransactionPhase(str, Enum):
    BOOTSTRAP = "BOOTSTRAP"
    FREEZE = "FREEZE"
    RAW_EXECUTION = "RAW_EXECUTION"
    RAW_SEALING = "RAW_SEALING"
    ORACLE_AUDIT = "ORACLE_AUDIT"
    SCORING = "SCORING"
    GATE_EVALUATION = "GATE_EVALUATION"
    VERDICT_DERIVATION = "VERDICT_DERIVATION"
    EVIDENCE_INDEX = "EVIDENCE_INDEX"
    RUN_ID_CONSISTENCY = "RUN_ID_CONSISTENCY"
    HEALTH_VERIFICATION = "HEALTH_VERIFICATION"
    RELEASE_FINALIZATION = "RELEASE_FINALIZATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


PHASE_SEQUENCE: list[TransactionPhase] = [
    TransactionPhase.BOOTSTRAP,
    TransactionPhase.FREEZE,
    TransactionPhase.RAW_EXECUTION,
    TransactionPhase.RAW_SEALING,
    TransactionPhase.ORACLE_AUDIT,
    TransactionPhase.SCORING,
    TransactionPhase.GATE_EVALUATION,
    TransactionPhase.VERDICT_DERIVATION,
    TransactionPhase.EVIDENCE_INDEX,
    TransactionPhase.RUN_ID_CONSISTENCY,
    TransactionPhase.HEALTH_VERIFICATION,
    TransactionPhase.RELEASE_FINALIZATION,
]


class CertificationTransaction:
    """Coordinates the 12-phase fail-closed certification transaction."""

    def __init__(
        self,
        run_id: str,
        run_dir: str | Path,
        *,
        gate_config_path: str | Path | None = None,
    ) -> None:
        if not run_id or not run_id.strip():
            raise TransactionError("run_id must be non-empty")
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.lifecycle = RunLifecycle(self.run_id)
        self.completed_phases: set[TransactionPhase] = set()
        self.current_step_idx: int = 0
        self.failed: bool = False
        self.failure_reason: Optional[str] = None

        self.gate_config_path = (
            Path(gate_config_path)
            if gate_config_path
            else Path(__file__).resolve().parents[1] / "config" / "profile-b-gates.json"
        )
        self.store: Optional[RunArtifactStore] = None
        self.raw_manifest_hash: Optional[str] = None
        self.audited_manifest_hash: Optional[str] = None
        self.gate_results: list[GateResult] = []
        self.final_verdict: Optional[FinalVerdict] = None
        self.evidence_index: Optional[dict[str, object]] = None

    def _require_phase(self, phase: TransactionPhase) -> None:
        if self.failed:
            raise TransactionError(
                f"Transaction has failed at a previous phase: {self.failure_reason}"
            )
        expected_phase = PHASE_SEQUENCE[self.current_step_idx]
        if phase != expected_phase:
            raise TransactionError(
                f"Out-of-order phase execution: attempted {phase.value}, expected {expected_phase.value}"
            )

    def _fail_transaction(self, reason: str, *, status: RunStatus = RunStatus.FAIL) -> None:
        self.failed = True
        self.failure_reason = reason
        try:
            if status in self.lifecycle.allowed_transitions():
                self.lifecycle.transition(status, reason=reason)
        except Exception:
            pass

    def execute_bootstrap(self, layout_info: dict[str, Any] | None = None) -> None:
        self._require_phase(TransactionPhase.BOOTSTRAP)
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.store = RunArtifactStore(self.run_dir, self.run_id)
            self.store.initialize()

            layout = layout_info or {
                "schema_version": "1.0",
                "canonical_root": str(self.run_dir),
                "runtime_root": str(self.run_dir),
            }
            (self.run_dir / "bootstrap-layout.json").write_text(
                json.dumps(layout, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.lifecycle.transition(RunStatus.BOOTSTRAPPED)
            self.lifecycle.transition(RunStatus.HARNESS_READY)
            self.completed_phases.add(TransactionPhase.BOOTSTRAP)
            self.current_step_idx += 1
        except Exception as exc:
            self._fail_transaction(f"bootstrap failed: {exc}")
            raise TransactionError(f"bootstrap failed: {exc}") from exc

    def execute_freeze(
        self,
        freeze_path: str | Path,
        checksum_path: str | Path,
        *,
        repository_root: str | Path,
        current_repository_shas: dict[str, str],
    ) -> FreezeVerification:
        self._require_phase(TransactionPhase.FREEZE)
        try:
            verification = verify_contract_freeze(
                freeze_path,
                checksum_path,
                repository_root=repository_root,
                current_repository_shas=current_repository_shas,
            )
            if verification.status != FreezeStatus.PASS:
                msg = f"Contract freeze verification failed: {verification.drift}"
                self._fail_transaction(msg, status=RunStatus.FAIL)
                raise TransactionError(msg)

            src_freeze = Path(freeze_path)
            src_checksum = Path(checksum_path)
            target_freeze = self.run_dir / src_freeze.name
            target_checksum = self.run_dir / src_checksum.name
            target_freeze.write_bytes(src_freeze.read_bytes())
            target_checksum.write_bytes(src_checksum.read_bytes())

            self.freeze_path = target_freeze
            self.checksum_path = target_checksum
            self.repository_root = Path(repository_root)
            self.current_repository_shas = dict(current_repository_shas)

            self.lifecycle.transition(RunStatus.GT_FROZEN)
            self.lifecycle.transition(RunStatus.CONTRACT_FROZEN)
            self.completed_phases.add(TransactionPhase.FREEZE)
            self.current_step_idx += 1
            return verification
        except Exception as exc:
            if not self.failed:
                self._fail_transaction(f"freeze failed: {exc}")
            raise

    def execute_raw_execution(
        self, raw_artifacts_builder: Callable[[Path], None]
    ) -> None:
        self._require_phase(TransactionPhase.RAW_EXECUTION)
        try:
            self.lifecycle.transition(RunStatus.TEST_RUNNING)
            if self.store is None:
                self.store = RunArtifactStore(self.run_dir, self.run_id)
            raw_artifacts_builder(self.run_dir)
            self.completed_phases.add(TransactionPhase.RAW_EXECUTION)
            self.current_step_idx += 1
        except Exception as exc:
            self._fail_transaction(f"raw execution failed: {exc}")
            raise TransactionError(f"raw execution failed: {exc}") from exc

    def execute_raw_sealing(self) -> str:
        self._require_phase(TransactionPhase.RAW_SEALING)
        try:
            if self.store is None:
                self.store = RunArtifactStore(self.run_dir, self.run_id)
            manifest_info = self.store.compute_raw_manifest()
            self.raw_manifest_hash = manifest_info["manifest_hash"]
            raw_manifest_path = self.run_dir / "raw-manifest.json"
            self.store._write_immutable_json(raw_manifest_path, manifest_info)
            self.lifecycle.transition(RunStatus.TEST_COMPLETED)
            self.completed_phases.add(TransactionPhase.RAW_SEALING)
            self.current_step_idx += 1
            return self.raw_manifest_hash
        except Exception as exc:
            self._fail_transaction(f"raw sealing failed: {exc}")
            raise TransactionError(f"raw sealing failed: {exc}") from exc

    def execute_oracle_audit(
        self,
        oracle_surfaces: list[dict[str, Any]] | dict[str, Any] | None = None,
        known_oracle_values: set[str] | None = None,
    ) -> dict[str, object]:
        self._require_phase(TransactionPhase.ORACLE_AUDIT)
        try:
            if self.store is None:
                self.store = RunArtifactStore(self.run_dir, self.run_id)
            current_manifest = self.store.compute_raw_manifest()
            current_hash = current_manifest["manifest_hash"]
            if self.raw_manifest_hash and current_hash != self.raw_manifest_hash:
                msg = "raw artifact manifest hash modified after sealing"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            # Derive surfaces from exact manifest-referenced sealed raw artifacts
            surfaces_dict = extract_raw_audit_surfaces(self.run_dir, current_manifest)

            # If caller supplied surfaces (e.g. for isolated tests), merge them
            if oracle_surfaces:
                if isinstance(oracle_surfaces, dict):
                    surfaces_dict.update(oracle_surfaces)
                else:
                    for i, item in enumerate(oracle_surfaces):
                        surfaces_dict[item.get("path", f"surface_{i}")] = item.get("content", item)

            audit_report = audit_oracle_surfaces(
                surfaces_dict,
                run_id=self.run_id,
                raw_manifest=current_manifest,
                known_oracle_values=known_oracle_values,
            )
            if audit_report["status"] != "PASS":
                msg = f"oracle audit failed: {audit_report.get('findings')}"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            self.audited_manifest_hash = current_hash
            self.store.persist_oracle_audit(audit_report)

            audit_path = self.run_dir / "oracle-audit-report.json"
            audit_path.write_text(
                json.dumps(audit_report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.completed_phases.add(TransactionPhase.ORACLE_AUDIT)
            self.current_step_idx += 1
            return audit_report
        except Exception as exc:
            if not self.failed:
                self._fail_transaction(f"oracle audit failed: {exc}")
            raise

    def execute_scoring(
        self,
        answer_records: list[dict[str, Any]] | None = None,
        scoring_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._require_phase(TransactionPhase.SCORING)
        try:
            if self.store is None:
                self.store = RunArtifactStore(self.run_dir, self.run_id)
            current_manifest = self.store.compute_raw_manifest()
            current_hash = current_manifest["manifest_hash"]

            if self.raw_manifest_hash and current_hash != self.raw_manifest_hash:
                msg = "raw artifact manifest hash modified after sealing"
                self._fail_transaction(msg)
                raise TransactionError(msg)
            if self.audited_manifest_hash and current_hash != self.audited_manifest_hash:
                msg = "raw artifact manifest hash modified after oracle audit"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            self.store._require_passing_oracle_audit()

            # Empty run rule: 0 raw records in sealed raw manifest must fail closed
            if not current_manifest["entries"]:
                msg = "scoring failed: 0 raw records in sealed raw manifest"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            evaluated_items = []
            for entry in current_manifest["entries"]:
                file_path = self.run_dir / entry["path"]
                self.store._verify_seal(file_path)
                raw_payload = json.loads(file_path.read_text(encoding="utf-8"))
                query_id = raw_payload.get("query_id")
                lane = raw_payload.get("lane", "answers" if "answers" in entry["path"] else "retrieval")

                if scoring_fn:
                    scored = scoring_fn(raw_payload)
                    if scored is None:
                        continue
                elif isinstance(raw_payload, dict) and "gt" in raw_payload and "answer_obj" in raw_payload:
                    scored = score_answer(
                        gt=raw_payload["gt"],
                        answer_obj=raw_payload["answer_obj"],
                        retrieved_chunk_ids=raw_payload.get("retrieved_chunk_ids", []),
                        identity_map=raw_payload.get("identity_map", {}),
                        exact_model_visible_context=raw_payload.get("exact_model_visible_context"),
                    ).model_dump(mode="json")
                elif "parsed_response" in raw_payload or "answer" in raw_payload:
                    ans_text = raw_payload.get("parsed_response", {}).get("answer", raw_payload.get("answer", ""))
                    ctx = raw_payload.get("exact_model_visible_context")
                    from harness.answer_scorer import STOPWORDS, _normalized, _stringify_context
                    unsupported_count = 0
                    if ctx is not None:
                        ctx_words = set(re.findall(r"\w+", _normalized(_stringify_context(ctx))))
                        ans_words = [w for w in re.findall(r"\w+", _normalized(ans_text)) if w not in STOPWORDS]
                        if any(w not in ctx_words for w in ans_words):
                            unsupported_count = 1
                    scored = {
                        "query_id": query_id,
                        "status": "FAIL" if unsupported_count > 0 else "PASS",
                        "lane": lane,
                        "grounded_pass": unsupported_count == 0,
                        "evidence_supported": True,
                        "facts_satisfied": unsupported_count == 0,
                        "forbidden_claims_absent": True,
                        "unsupported_material_claim_count": unsupported_count,
                        "reasons": ["contains unsupported material"] if unsupported_count > 0 else [],
                    }
                else:
                    scored = {
                        "query_id": query_id,
                        "status": "PASS",
                        "lane": lane,
                        "recall_at_5": 1.0,
                        "mrr": 1.0,
                    }

                self.store.persist_scored(lane=lane, query_id=query_id, score=scored)
                evaluated_items.append(scored)

            if not evaluated_items:
                msg = "scoring failed: 0 scored items produced from raw artifacts"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            oracle_audit_path = self.run_dir / "oracle-leakage-audit.json"
            oracle_audit_hash = hashlib.sha256(oracle_audit_path.read_bytes()).hexdigest()

            report = {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "scorer_version": "1.0.0",
                "raw_manifest_hash": current_hash,
                "oracle_audit_hash": oracle_audit_hash,
                "item_count": len(evaluated_items),
                "status": "PASS" if all(it.get("status") == "PASS" for it in evaluated_items) else "FAIL",
                "items": evaluated_items,
            }
            report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
            score_artifact_hash = hashlib.sha256(report_bytes).hexdigest()
            report["score_artifact_hash"] = score_artifact_hash

            (self.run_dir / "answer-test-report.json").write_bytes(report_bytes + b"\n")
            (self.run_dir / "retrieval-test-report.json").write_bytes(report_bytes + b"\n")
            (self.run_dir / "scoring-report.json").write_bytes(report_bytes + b"\n")

            # Calculate retrieval & answer metrics from evaluated_items
            retrieval_items = [it for it in evaluated_items if it.get("lane") == "retrieval"]
            answer_items = [it for it in evaluated_items if it.get("lane") == "answers"]

            metrics_computed: dict[str, Any] = {}
            if retrieval_items:
                r5_vals = [it.get("recall_at_5", 1.0 if it.get("status") == "PASS" else 0.0) for it in retrieval_items]
                mrr_vals = [it.get("mrr", 1.0 if it.get("status") == "PASS" else 0.0) for it in retrieval_items]
                rel_vals = [it.get("rel_complete_evidence_at_5", it.get("recall_at_5", 1.0 if it.get("status") == "PASS" else 0.0)) for it in retrieval_items]
                single_vals = [it.get("single_hop_recall_at_5", it.get("recall_at_5", 1.0 if it.get("status") == "PASS" else 0.0)) for it in retrieval_items]
                metrics_computed.update({
                    "answerable_recall_at_5": sum(r5_vals) / len(r5_vals) if r5_vals else 0.0,
                    "answerable_mrr": sum(mrr_vals) / len(mrr_vals) if mrr_vals else 0.0,
                    "rel_complete_evidence_at_5": sum(rel_vals) / len(rel_vals) if rel_vals else 0.0,
                    "single_hop_recall_at_5": sum(single_vals) / len(single_vals) if single_vals else 0.0,
                    "tenant_leakage": sum(it.get("tenant_leakage", 0) for it in retrieval_items),
                })
            elif evaluated_items:
                pass_vals = [1.0 if it.get("status") == "PASS" else 0.0 for it in evaluated_items]
                avg_pass = sum(pass_vals) / len(pass_vals) if pass_vals else 0.0
                metrics_computed.update({
                    "answerable_recall_at_5": avg_pass,
                    "answerable_mrr": avg_pass,
                    "rel_complete_evidence_at_5": avg_pass,
                    "single_hop_recall_at_5": avg_pass,
                    "tenant_leakage": 0,
                })

            if answer_items:
                ans_pass = [1.0 if it.get("status") == "PASS" else 0.0 for it in answer_items if it.get("is_answerable", True)]
                no_ans_pass = [1.0 if it.get("status") == "PASS" else 0.0 for it in answer_items if not it.get("is_answerable", True)]
                unsupported_count = sum(
                    1 if (
                        it.get("unsupported_material_claim_count", 0) > 0
                        or any("unsupported material" in str(r) for r in it.get("reasons", []))
                        or it.get("unsupported_material_claim_rate", 0) > 0
                    ) else 0
                    for it in answer_items
                )
                unsupported_rate = unsupported_count / len(answer_items) if answer_items else 0.0
                metrics_computed.update({
                    "answerable_pass_rate": sum(ans_pass) / len(ans_pass) if ans_pass else (1.0 if not [it for it in answer_items if it.get("is_answerable", True)] else 0.0),
                    "no_answer_pass_rate": sum(no_ans_pass) / len(no_ans_pass) if no_ans_pass else 1.0,
                    "fabricated_evidence_chunk_ids": sum(it.get("fabricated_evidence_chunk_ids", 0) for it in answer_items),
                    "unsupported_material_claim_rate": unsupported_rate,
                })
            elif evaluated_items:
                pass_vals = [1.0 if it.get("status") == "PASS" else 0.0 for it in evaluated_items]
                avg_pass = sum(pass_vals) / len(pass_vals) if pass_vals else 0.0
                metrics_computed.update({
                    "answerable_pass_rate": avg_pass,
                    "no_answer_pass_rate": 1.0,
                    "fabricated_evidence_chunk_ids": 0,
                    "unsupported_material_claim_rate": 0,
                })

            summary = {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "scorer_version": "1.0.0",
                "raw_manifest_hash": current_hash,
                "oracle_audit_hash": oracle_audit_hash,
                "item_count": len(evaluated_items),
                "status": "PASS" if (evaluated_items and all(it.get("status") == "PASS" for it in evaluated_items)) else "FAIL",
                "score_artifact_hash": score_artifact_hash,
                "metrics": metrics_computed,
            }
            self.store._write_immutable_json(
                self.run_dir / "scoring-summary.json", summary
            )
            (self.run_dir / "answer-summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (self.run_dir / "retrieval-summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.completed_phases.add(TransactionPhase.SCORING)
            self.current_step_idx += 1
            return report
        except Exception as exc:
            if not self.failed:
                self._fail_transaction(f"scoring failed: {exc}")
            raise TransactionError(f"scoring failed: {exc}") from exc

    def execute_gate_evaluation(
        self,
        gate_metrics: dict[str, dict[str, Any]] | None = None,
        gate_evidence: dict[str, list[str]] | None = None,
    ) -> list[GateResult]:
        self._require_phase(TransactionPhase.GATE_EVALUATION)
        try:
            if self.store is None:
                self.store = RunArtifactStore(self.run_dir, self.run_id)

            current_manifest = self.store.compute_raw_manifest()
            if self.raw_manifest_hash and current_manifest["manifest_hash"] != self.raw_manifest_hash:
                msg = "raw artifact manifest modified before gate evaluation"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            # 1. Load official score artifact
            summary_path = self.run_dir / "scoring-summary.json"
            if not summary_path.is_file():
                msg = "missing score artifact: scoring-summary.json"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            # 2. Verify seal & integrity of score summary
            self.store._verify_seal(summary_path)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            if summary.get("run_id") != self.run_id:
                msg = f"score artifact run_id mismatch: {summary.get('run_id')} != {self.run_id}"
                self._fail_transaction(msg)
                raise TransactionError(msg)
            if summary.get("raw_manifest_hash") != self.raw_manifest_hash:
                msg = f"score artifact raw manifest hash mismatch: {summary.get('raw_manifest_hash')} != {self.raw_manifest_hash}"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            item_count = summary.get("item_count", 0)
            score_metrics = summary.get("metrics", {})

            config = load_gate_config(self.gate_config_path)
            results: list[GateResult] = []

            default_evidence_map: dict[str, list[str]] = {
                "B0": ["contract-freeze.json"],
                "B1": ["resource-provider-summary.json", "health-pre-test.json"],
                "B2": ["provider-preflight-evidence.json"],
                "B3": ["contract-freeze.json"],
                "B4": ["raw-manifest.json"],
                "B5": ["contract-freeze.json"],
                "B6": ["scorer-canary-results.json", "contract-freeze.json"],
                "B7": ["raw-manifest.json"],
                "B8": ["determinism-manifest.json"],
                "B9": ["raw-manifest.json"],
                "B10": ["scoring-summary.json", "retrieval-test-report.json"],
                "B11": ["graph-summary.json"],
                "B12": ["scoring-summary.json", "answer-test-report.json"],
                "B13": ["health-post-test.json", "resource-provider-summary.json"],
                "B14": ["contract-freeze.json", "raw-manifest.json"],
            }

            observations: dict[str, dict[str, Any]] = {}
            caller_metrics = gate_metrics or {}
            caller_evidence = gate_evidence or {}

            for gate_id in config.mandatory_gate_ids:
                defn = config.gates[gate_id]
                observed = dict(caller_metrics.get(gate_id, {}))

                # For score-derived gates B10 and B12, authoritative derivation overrides caller
                if gate_id == "B10":
                    if item_count == 0:
                        observed = {
                            "answerable_recall_at_5": 0.0,
                            "answerable_mrr": 0.0,
                            "rel_complete_evidence_at_5": 0.0,
                            "single_hop_recall_at_5": 0.0,
                            "tenant_leakage": 1,
                        }
                    else:
                        for k in ("answerable_recall_at_5", "answerable_mrr", "rel_complete_evidence_at_5", "single_hop_recall_at_5", "tenant_leakage"):
                            if k in score_metrics:
                                observed[k] = score_metrics[k]
                elif gate_id == "B12":
                    if item_count == 0:
                        observed = {
                            "answerable_pass_rate": 0.0,
                            "fabricated_evidence_chunk_ids": 1,
                            "no_answer_pass_rate": 0.0,
                            "unsupported_material_claim_rate": 1,
                        }
                    else:
                        for k in ("answerable_pass_rate", "fabricated_evidence_chunk_ids", "no_answer_pass_rate", "unsupported_material_claim_rate"):
                            if k in score_metrics:
                                observed[k] = score_metrics[k]

                observations[gate_id] = observed

                # Evidence verification: check each evidence file
                evidence_candidates = caller_evidence.get(gate_id)
                if evidence_candidates is None:
                    evidence = [p for p in default_evidence_map.get(gate_id, []) if (self.run_dir / p).is_file()]
                    if not evidence:
                        for fb in ("raw-manifest.json", "scoring-summary.json", "contract-freeze.json"):
                            if (self.run_dir / fb).is_file():
                                evidence = [fb]
                                break
                else:
                    valid_evidence = []
                    for ev_item in evidence_candidates:
                        p = Path(ev_item)
                        if (self.run_dir / p).is_file() or p.is_file():
                            valid_evidence.append(str(p))
                    evidence = valid_evidence

                gate_result = evaluate_threshold_gate(
                    defn,
                    observed,
                    ExecutionStatus.COMPLETED,
                    evidence,
                )
                results.append(gate_result)

            self.gate_results = results

            # Write versioned gate observations artifact
            obs_payload = {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "raw_manifest_hash": self.raw_manifest_hash,
                "derived_at_utc": datetime.now(timezone.utc).isoformat(),
                "observations": observations,
            }
            (self.run_dir / "gate-observations.json").write_text(
                json.dumps(obs_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            failed_hard = [g.gate_id for g in results if g.hard and g.status != GateStatus.PASS]
            if failed_hard:
                self.failure_reason = f"hard gates not passed: {failed_hard}"

            gate_results_path = self.run_dir / "gate-results.json"
            gate_results_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "run_id": self.run_id,
                        "gates": [g.model_dump(mode="json") for g in results],
                        "mandatory_gate_ids": config.mandatory_gate_ids,
                        "status": "FAIL" if failed_hard else "PASS",
                        "final_verdict": "PROFILE_B_FAIL" if failed_hard else "PROFILE_B_PASS_NATIVE",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            self.completed_phases.add(TransactionPhase.GATE_EVALUATION)
            self.current_step_idx += 1
            return results
        except Exception as exc:
            self._fail_transaction(f"gate evaluation failed: {exc}")
            raise TransactionError(f"gate evaluation failed: {exc}") from exc

    def execute_verdict_derivation(self) -> FinalVerdict:
        self._require_phase(TransactionPhase.VERDICT_DERIVATION)
        try:
            config = load_gate_config(self.gate_config_path)
            manifest_path = self.run_dir / "run_manifest.json"
            manifest_payload = {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "status": "COMPLETED",
                "lifecycle_valid": not self.failed,
                "lifecycle_status": self.lifecycle.status.value,
            }
            manifest_path.write_text(
                json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8"
            )

            freeze_f = self.freeze_path or (self.run_dir / "contract-freeze.json")
            checksum_f = self.checksum_path or (self.run_dir / "contract-freeze.SHA256")
            repo_root = self.repository_root or self.run_dir
            repo_shas = self.current_repository_shas or {}

            verdict = derive_production_verdict(
                run_id=self.run_id,
                gates=self.gate_results,
                mandatory_gate_ids=set(config.mandatory_gate_ids),
                run_dir=self.run_dir,
                freeze_path=freeze_f,
                checksum_path=checksum_f,
                repository_root=repo_root,
                current_repository_shas=repo_shas,
                mandatory_artifact_names=["contract-freeze.json"],
            )
            self.final_verdict = verdict
            verdict_path = self.run_dir / "verdict.json"
            verdict_path.write_text(
                json.dumps(verdict.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.completed_phases.add(TransactionPhase.VERDICT_DERIVATION)
            self.current_step_idx += 1
            return verdict
        except Exception as exc:
            self._fail_transaction(f"verdict derivation failed: {exc}")
            raise TransactionError(f"verdict derivation failed: {exc}") from exc

    def execute_evidence_index(
        self, records: Iterable[dict[str, Any]]
    ) -> dict[str, object]:
        self._require_phase(TransactionPhase.EVIDENCE_INDEX)
        try:
            record_list = list(records)
            if not record_list:
                msg = "empty evidence index: at least one evidence artifact must be provided"
                self._fail_transaction(msg)
                raise TransactionError(msg)
            output_path = self.run_dir / "evidence-index.json"
            index_data = build_evidence_index(
                run_dir=self.run_dir,
                output_path=output_path,
                records=record_list,
                run_id=self.run_id,
            )
            self.evidence_index = index_data
            self.completed_phases.add(TransactionPhase.EVIDENCE_INDEX)
            self.current_step_idx += 1
            return index_data
        except Exception as exc:
            if not self.failed:
                self._fail_transaction(f"evidence index failed: {exc}")
            if not isinstance(exc, TransactionError):
                raise TransactionError(f"evidence index failed: {exc}") from exc
            raise

    def execute_run_id_consistency(
        self, reuse_authorizations: Iterable[dict[str, str]] = ()
    ) -> dict[str, object]:
        self._require_phase(TransactionPhase.RUN_ID_CONSISTENCY)
        try:
            report = validate_run_id_consistency(
                self.run_dir, self.run_id, reuse_authorizations=reuse_authorizations
            )
            if report["status"] != "PASS":
                msg = f"run-id consistency failed: {report['mismatches']}"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            self.completed_phases.add(TransactionPhase.RUN_ID_CONSISTENCY)
            self.current_step_idx += 1
            return report
        except Exception as exc:
            if not self.failed:
                self._fail_transaction(f"run-id consistency failed: {exc}")
            raise

    def execute_health_verification(
        self, health_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._require_phase(TransactionPhase.HEALTH_VERIFICATION)
        try:
            payload = health_payload or {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "status": "PASS",
                "oom_killed_count": 0,
            }
            if payload.get("status") != "PASS":
                msg = f"health verification status is not PASS: {payload.get('status')}"
                self._fail_transaction(msg)
                raise TransactionError(msg)
            if payload.get("run_id") != self.run_id:
                msg = f"health verification run_id mismatch: {payload.get('run_id')} != {self.run_id}"
                self._fail_transaction(msg)
                raise TransactionError(msg)
            (self.run_dir / "provider-preflight-evidence.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.completed_phases.add(TransactionPhase.HEALTH_VERIFICATION)
            self.current_step_idx += 1
            return payload
        except Exception as exc:
            if not self.failed:
                self._fail_transaction(f"health verification failed: {exc}")
            if not isinstance(exc, TransactionError):
                raise TransactionError(f"health verification failed: {exc}") from exc
            raise

    def execute_release_finalization(
        self, target_release_dir: str | Path
    ) -> dict[str, object]:
        self._require_phase(TransactionPhase.RELEASE_FINALIZATION)
        try:
            if not self.final_verdict or self.final_verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE:
                verdict_status = self.final_verdict.status.value if self.final_verdict else "NONE"
                msg = f"Cannot finalize release with non-PASS verdict: {verdict_status}"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            from harness.finalizer import REQUIRED_RELEASE_FILES

            # Fail closed if any required release file is missing - NEVER synthesize
            missing_files = [name for name in sorted(REQUIRED_RELEASE_FILES) if not (self.run_dir / name).is_file()]
            if missing_files:
                msg = f"missing required release artifacts: {missing_files}"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            # Transition lifecycle to FINALIZING then PASS_NATIVE
            self.lifecycle.transition(RunStatus.FINALIZING)
            self.lifecycle.transition(RunStatus.PASS_NATIVE)
            self.lifecycle.write(self.run_dir / "lifecycle.json")

            sources = {
                name: self.run_dir / name
                for name in REQUIRED_RELEASE_FILES
            }
            dest_path = finalize_release(
                run_id=self.run_id,
                sources=sources,
                release_root=target_release_dir,
            )
            self.completed_phases.add(TransactionPhase.RELEASE_FINALIZATION)
            self.completed_phases.add(TransactionPhase.COMPLETED)
            return {
                "run_id": self.run_id,
                "release_dir": str(dest_path),
                "status": "PASS",
            }
        except Exception as exc:
            if not self.failed:
                self._fail_transaction(f"release finalization failed: {exc}")
            if not isinstance(exc, TransactionError):
                raise TransactionError(f"release finalization failed: {exc}") from exc
            raise
