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
        if not 0 <= self.current_step_idx < len(PHASE_SEQUENCE):
            raise TransactionError("phase sequence already completed or corrupted")
        if self.completed_phases != set(PHASE_SEQUENCE[:self.current_step_idx]):
            raise TransactionError("phase history does not match current phase")
        replay = RunLifecycle(self.run_id)
        try:
            for event in self.lifecycle.history:
                if event["from"] != replay.status.value:
                    raise ValueError("discontinuous lifecycle history")
                replay.transition(RunStatus(event["to"]))
            expected_status = (
                RunStatus.CREATED if self.current_step_idx == 0 else
                RunStatus.HARNESS_READY if self.current_step_idx == 1 else
                RunStatus.CONTRACT_FROZEN if self.current_step_idx == 2 else
                RunStatus.TEST_RUNNING if self.current_step_idx == 3 else
                RunStatus.TEST_COMPLETED
            )
            if replay.status != self.lifecycle.status or replay.status != expected_status:
                raise ValueError("lifecycle status does not match phase")
        except (KeyError, ValueError, RuntimeError) as exc:
            raise TransactionError(f"invalid lifecycle: {exc}") from exc
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
            self._gate_config_hash = hashlib.sha256(self.gate_config_path.read_bytes()).hexdigest()
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
                    surfaces_dict = {"sealed_raw": surfaces_dict, "supplemental": oracle_surfaces}
                else:
                    surfaces_dict = {"sealed_raw": surfaces_dict, "supplemental": oracle_surfaces}

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

                # The MESA response/context adapters and frozen GT join are not
                # independently verified yet. Raw bytes alone cannot establish
                # correctness; neither a callback nor a word-overlap heuristic is
                # an official scorer. Keep this phase inspectable but non-PASS.
                scored = {
                    "query_id": query_id,
                    "lane": lane,
                    "status": "UNVERIFIED",
                    "reasons": ["WAIT_FOR_MESA: frozen scorer/input binding unavailable"],
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
                "scorer_version": "unverified-adapter-1",
                "scorer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "raw_manifest_hash": current_hash,
                "oracle_audit_hash": oracle_audit_hash,
                "item_count": len(evaluated_items),
                "status": "PASS" if all(it.get("status") == "PASS" for it in evaluated_items) else "FAIL",
                "items": evaluated_items,
            }
            report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
            score_artifact_hash = hashlib.sha256(report_bytes + b"\n").hexdigest()
            report["score_artifact_hash"] = score_artifact_hash

            (self.run_dir / "answer-test-report.json").write_bytes(report_bytes + b"\n")
            (self.run_dir / "retrieval-test-report.json").write_bytes(report_bytes + b"\n")
            (self.run_dir / "scoring-report.json").write_bytes(report_bytes + b"\n")

            # Missing measured populations have no metrics. In particular an
            # answer lane must never manufacture retrieval or NO_ANSWER results.
            metrics_computed: dict[str, Any] = {}

            summary = {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "scorer_version": "unverified-adapter-1",
                "scorer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
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

            self.store._require_passing_oracle_audit()
            oracle_hash = hashlib.sha256((self.run_dir / "oracle-leakage-audit.json").read_bytes()).hexdigest()
            if summary.get("oracle_audit_hash") != oracle_hash:
                raise TransactionError("ORACLE_AUDIT_STALE: score artifact audit hash mismatch")
            report_path = self.run_dir / "scoring-report.json"
            if not report_path.is_file() or hashlib.sha256(report_path.read_bytes()).hexdigest() != summary.get("score_artifact_hash"):
                raise TransactionError("score report hash mismatch")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("item_count") != summary.get("item_count") or len(report.get("items", [])) != summary.get("item_count"):
                raise TransactionError("score item count mismatch")
            if summary.get("scorer_sha256") != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
                raise TransactionError("scorer source hash mismatch")

            item_count = summary.get("item_count", 0)
            score_metrics = summary.get("metrics", {})

            config = load_gate_config(self.gate_config_path)
            results: list[GateResult] = []

            verification = verify_contract_freeze(
                self.freeze_path, self.checksum_path,
                repository_root=self.repository_root,
                current_repository_shas=self.current_repository_shas,
            )
            if verification.status != FreezeStatus.PASS:
                raise TransactionError(f"freeze invalid before gates: {verification.drift}")
            if hashlib.sha256(self.gate_config_path.read_bytes()).hexdigest() != self._gate_config_hash:
                raise TransactionError("threshold config changed after freeze")

            observations: dict[str, dict[str, Any]] = {}
            for gate_id in config.mandatory_gate_ids:
                defn = config.gates[gate_id]
                # No current producer proves these gate observations from a
                # verified MESA contract. Do not adopt caller metrics or an
                # unrelated existing path as evidence. Keep each gate explicit.
                observed: dict[str, Any] = {}
                observations[gate_id] = observed
                results.append(GateResult(
                    gate_id=gate_id, hard=defn.hard,
                    execution_status=ExecutionStatus.COMPLETED,
                    status=GateStatus.UNVERIFIED,
                    required={k: v.model_dump(mode="json") for k, v in defn.requirements.items()},
                    observed=observed, evidence=[],
                    reason="authoritative_metric_producer_unavailable",
                ))

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
            from harness.operations import verify_health_artifacts
            payload = verify_health_artifacts(self.run_dir, self.run_id)
            if payload["status"] != "PASS":
                raise TransactionError(f"health verification failed: {payload['reasons']}")
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
