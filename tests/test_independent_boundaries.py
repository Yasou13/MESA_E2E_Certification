"""Second-sweep attacks on producer and lifecycle boundaries."""
import hashlib
import json

import pytest

from tests.independent_support import transaction
from harness.freeze import verify_contract_freeze, FreezeStatus
from harness.verdict import derive_production_verdict
from harness.models import GateResult, VerdictStatus
from harness.transaction import TransactionError, TransactionPhase


def reseal(path):
    path.with_suffix(path.suffix + ".SHA256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n")


def test_production_verdict_rejects_caller_gate_registry(tmp_path):
    tx = transaction(tmp_path)
    (tx.run_dir / "run_manifest.json").write_text(json.dumps({
        "schema_version": "1.0", "run_id": tx.run_id, "status": "COMPLETED", "lifecycle_valid": True}))
    gate = GateResult(gate_id="B10", hard=True, execution_status="COMPLETED", status="PASS",
        required={}, observed={}, reason="caller", evidence=["anything"])
    verdict = derive_production_verdict(run_id=tx.run_id, gates=[gate], mandatory_gate_ids={"B10"},
        run_dir=tx.run_dir, freeze_path=tx.freeze_path, checksum_path=tx.checksum_path,
        repository_root=tx.repository_root, current_repository_shas=tx.current_repository_shas,
        mandatory_artifact_names=[])
    assert verdict.status != VerdictStatus.PROFILE_B_PASS_NATIVE


def test_lifecycle_corruption_blocks_oracle_phase(tmp_path):
    tx = transaction(tmp_path)
    tx.lifecycle.history.clear()
    with pytest.raises(TransactionError, match="lifecycle"):
        tx.execute_oracle_audit()


def test_phase_counter_cannot_skip_oracle_audit(tmp_path):
    tx = transaction(tmp_path)
    tx.current_step_idx += 1
    with pytest.raises(TransactionError, match="phase|lifecycle"):
        tx.execute_scoring()


@pytest.mark.parametrize("mutation", ["empty_material", "empty_runtime"])
def test_semantically_empty_freeze_rejected(tmp_path, mutation):
    tx = transaction(tmp_path)
    pl = json.loads(tx.freeze_path.read_text())
    if mutation == "empty_material":
        material = pl["materials"][0]
        (tx.repository_root / material["path"]).write_bytes(b"")
        material["sha256"] = hashlib.sha256(b"").hexdigest()
    else:
        pl["runtime_identities"] = {}
    tx.freeze_path.write_text(json.dumps(pl))
    tx.checksum_path.write_text(hashlib.sha256(tx.freeze_path.read_bytes()).hexdigest()+"  contract-freeze.json\n")
    result = verify_contract_freeze(tx.freeze_path, tx.checksum_path,
        repository_root=tx.repository_root, current_repository_shas=tx.current_repository_shas)
    assert result.status != FreezeStatus.PASS


def test_oracle_audit_must_match_run_identity(tmp_path):
    tx = transaction(tmp_path)
    tx.execute_oracle_audit()
    path = tx.run_dir / "oracle-leakage-audit.json"
    pl = json.loads(path.read_text())
    pl["run_id"] = "RUN-foreign"
    path.write_text(json.dumps(pl))
    reseal(path)
    with pytest.raises(TransactionError, match="oracle|run_id"):
        tx.execute_scoring()


def test_raw_run_identity_checked_before_oracle(tmp_path):
    tx = transaction(tmp_path)
    path = tx.run_dir / "raw/retrieval/Q-audit.json"
    pl = json.loads(path.read_text())
    pl["run_id"] = "RUN-foreign"
    path.write_text(json.dumps(pl))
    reseal(path)
    # Direct store checks must reject a resealed foreign record, independently
    # of the transaction's separately pinned manifest.
    with pytest.raises(Exception, match="run_id|identity"):
        tx.store.compute_raw_manifest()
