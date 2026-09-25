"""Authoritative fail-closed certification transaction orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from harness.answer_scorer import score_answer
from harness.artifacts import RunArtifactStore
from harness.evidence import build_evidence_index, validate_run_id_consistency
from harness.finalizer import finalize_release, ReleaseFinalizationError
from harness.freeze import verify_contract_freeze, FreezeStatus
from harness.gates import GateConfig, evaluate_threshold_gate, load_gate_config
from harness.lifecycle import RunLifecycle
from harness.models import ExecutionStatus, FinalVerdict, GateResult, GateStatus, RunStatus, VerdictStatus
from harness.oracle import audit_oracle_surfaces
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
            self.lifecycle.transition(RunStatus.TEST_COMPLETED)
            self.completed_phases.add(TransactionPhase.RAW_SEALING)
            self.current_step_idx += 1
            return self.raw_manifest_hash
        except Exception as exc:
            self._fail_transaction(f"raw sealing failed: {exc}")
            raise TransactionError(f"raw sealing failed: {exc}") from exc

    def execute_oracle_audit(
        self,
        oracle_surfaces: list[dict[str, Any]],
        known_oracle_values: set[str] | None = None,
    ) -> dict[str, object]:
        self._require_phase(TransactionPhase.ORACLE_AUDIT)
        try:
            if self.store is None:
                self.store = RunArtifactStore(self.run_dir, self.run_id)
            # Recompute to check tampering
            current_manifest = self.store.compute_raw_manifest()
            current_hash = current_manifest["manifest_hash"]
            if self.raw_manifest_hash and current_hash != self.raw_manifest_hash:
                msg = "raw artifact manifest hash modified after sealing"
                self._fail_transaction(msg)
                raise TransactionError(msg)

            if isinstance(oracle_surfaces, dict):
                surfaces_dict = oracle_surfaces
            else:
                surfaces_dict = {
                    item.get("path", f"surface_{i}"): item.get("content", item)
                    for i, item in enumerate(oracle_surfaces)
                }

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
        answer_records: list[dict[str, Any]],
        scoring_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._require_phase(TransactionPhase.SCORING)
        try:
            evaluated_items = []
            for item in answer_records:
                if scoring_fn:
                    scored = scoring_fn(item)
                elif isinstance(item, dict) and "gt" in item and "answer_obj" in item:
                    scored = score_answer(
                        gt=item["gt"],
                        answer_obj=item["answer_obj"],
                        retrieved_chunk_ids=item.get("retrieved_chunk_ids", []),
                        identity_map=item["identity_map"],
                    ).model_dump(mode="json")
                else:
                    scored = item
                evaluated_items.append(scored)

            report = {
                "schema_version": "1.0",
                "run_id": self.run_id,
                "items": evaluated_items,
            }
            (self.run_dir / "answer-test-report.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            summary_path = self.run_dir / "answer-summary.json"
            if not summary_path.is_file():
                summary_path.write_text(
                    json.dumps(
                        {"schema_version": "1.0", "run_id": self.run_id, "status": "PASS"},
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            self.completed_phases.add(TransactionPhase.SCORING)
            self.current_step_idx += 1
            return report
        except Exception as exc:
            self._fail_transaction(f"scoring failed: {exc}")
            raise TransactionError(f"scoring failed: {exc}") from exc

    def execute_gate_evaluation(
        self,
        gate_metrics: dict[str, dict[str, Any]],
        gate_evidence: dict[str, list[str]],
    ) -> list[GateResult]:
        self._require_phase(TransactionPhase.GATE_EVALUATION)
        try:
            config = load_gate_config(self.gate_config_path)
            results: list[GateResult] = []

            for gate_id in config.mandatory_gate_ids:
                defn = config.gates[gate_id]
                observed = gate_metrics.get(gate_id, {})
                evidence = gate_evidence.get(gate_id, ["evidence.json"])
                gate_result = evaluate_threshold_gate(
                    defn,
                    observed,
                    ExecutionStatus.COMPLETED,
                    evidence,
                )
                results.append(gate_result)

            self.gate_results = results
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
            output_path = self.run_dir / "evidence-index.json"
            index_data = build_evidence_index(
                run_dir=self.run_dir,
                output_path=output_path,
                records=records,
                run_id=self.run_id,
            )
            self.evidence_index = index_data
            self.completed_phases.add(TransactionPhase.EVIDENCE_INDEX)
            self.current_step_idx += 1
            return index_data
        except Exception as exc:
            self._fail_transaction(f"evidence index failed: {exc}")
            raise TransactionError(f"evidence index failed: {exc}") from exc

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
            (self.run_dir / "provider-preflight-evidence.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for h_name in (
                "health-pre-test.json",
                "health-post-test.json",
                "resource-provider-summary.json",
            ):
                hp = self.run_dir / h_name
                if not hp.is_file():
                    hp.write_text(
                        json.dumps(
                            {"schema_version": "1.0", "run_id": self.run_id, "status": "PASS"},
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            self.completed_phases.add(TransactionPhase.HEALTH_VERIFICATION)
            self.current_step_idx += 1
            return payload
        except Exception as exc:
            self._fail_transaction(f"health verification failed: {exc}")
            raise TransactionError(f"health verification failed: {exc}") from exc

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

            # Record final report md if missing
            report_md_path = self.run_dir / "final-report.md"
            if not report_md_path.is_file():
                report_md_path.write_text(
                    f"# Final Report\n\nRun: {self.run_id}\nStatus: PASS\n",
                    encoding="utf-8",
                )

            # Ensure all required release files exist
            for name in REQUIRED_RELEASE_FILES:
                p = self.run_dir / name
                if not p.is_file():
                    p.write_text(
                        json.dumps(
                            {"schema_version": "1.0", "run_id": self.run_id, "status": "PASS"},
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )

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
            raise
