"""A1-A30 against independently constructed production transactions.

PASS means an attack was blocked. This suite does not assert that deferred
runtime adapters can produce an authorized successful certification.
"""
import hashlib
import json

import pytest

from tests.independent_support import transaction, placeholder_sources, score_claims, NOW
from harness.artifacts import ArtifactStoreError
from harness.evidence import EvidenceIndexError, build_evidence_index, validate_run_id_consistency
from harness.finalizer import finalize_release, ReleaseFinalizationError
from harness.freeze import verify_contract_freeze, FreezeStatus
from harness.models import VerdictStatus
from harness.transaction import CertificationTransaction, TransactionError


def record(tx, path="raw/retrieval/Q-audit.json"):
    return {"path": path, "producer": "independent", "phase": "test",
            "timestamp_utc": NOW, "source_run_id": tx.run_id,
            "immutable": True, "sealed": True}


def reseal(path):
    path.with_suffix(path.suffix + ".SHA256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest()+"  "+path.name+"\n")


@pytest.mark.parametrize("attack", [f"A{i}" for i in range(1,31)])
def test_attack(attack, tmp_path):
    if attack in {"A12", "A13", "A14", "A15", "A16", "A17"}:
        sources = placeholder_sources(tmp_path)
        if attack in {"A14", "A15", "A16"}:
            name = {"A14": "health-pre-test.json", "A15": "determinism-manifest.json",
                    "A16": "scorer-canary-results.json"}[attack]
            sources[name].unlink()
        if attack == "A12":
            p = sources["gate-results.json"]
            payload = json.loads(p.read_text())
            payload["gates"][0]["status"] = "FAIL"
            p.write_text(json.dumps(payload))
        with pytest.raises(ReleaseFinalizationError):
            finalize_release(run_id="RUN-independent", sources=sources, release_root=tmp_path / "release")
        assert not (tmp_path / "release" / "RUN-independent").exists()
        return
    if attack in {"A18", "A19", "A20", "A21"}:
        text = {"A18": "Ceza 5 yıldır sürgün", "A19": "Ceza 5 yıldır ve 100 milyon TL tazminat vardır",
                "A20": "Ceza 5 yıl değildir", "A21": "Ceza 5 yıldır [FABRICATED-ID]"}[attack]
        assert score_claims([text]).status != "PASS"
        return
    request = {"required_facts": ["SECRET-FACT"]} if attack == "A4" else (
        {"metadata": {"debug": "SECRET-FACT"}} if attack == "A5" else None)
    tx = transaction(tmp_path, request=request, empty=attack == "A1")
    raw = tx.run_dir / "raw/retrieval/Q-audit.json"
    if attack in {"A4", "A5"}:
        with pytest.raises(TransactionError, match="oracle audit failed"):
            tx.execute_oracle_audit([], known_oracle_values={"SECRET-FACT"})
        return
    if attack == "A1":
        assert tx.store.compute_raw_manifest()["entries"] == []
        with pytest.raises(TransactionError, match="oracle audit failed"):
            tx.execute_oracle_audit()
        return
    if attack == "A24":
        tx.current_step_idx += 1
        with pytest.raises(TransactionError, match="phase history"):
            tx.execute_scoring()
        return
    if attack == "A28":
        p = tx.repository_root / "ground_truth.txt"
        p.write_bytes(b"")
        result = verify_contract_freeze(tx.freeze_path, tx.checksum_path,
            repository_root=tx.repository_root, current_repository_shas=tx.current_repository_shas)
        assert result.status != FreezeStatus.PASS
        return
    tx.execute_oracle_audit()
    if attack in {"A6", "A7", "A8", "A30"}:
        if attack == "A6":
            raw.write_text(raw.read_text()+" ")
        elif attack == "A7":
            tx.store.persist_raw_retrieval(query_id="Q-added", request={"query": "new"},
                response={"results": []}, transport_status=200, timestamp_utc=NOW,
                latency_ms=1, runtime_lock_sha256="0"*64)
        elif attack == "A8":
            raw.unlink()
        else:
            p = tx.run_dir / "oracle-leakage-audit.json"
            pl = json.loads(p.read_text()); pl["raw_manifest_hash"] = "0" * 64
            p.write_text(json.dumps(pl)); reseal(p)
        with pytest.raises(TransactionError, match="manifest|mutated|STALE"):
            tx.execute_scoring()
        return
    if attack == "A9":
        report = tx.execute_scoring(answer_records=[{"query_id": "INJECTED", "status": "PASS"}])
        assert report["status"] != "PASS"
        assert all(i["query_id"] == "Q-audit" for i in report["items"])
        return
    tx.execute_scoring()
    if attack in {"A2", "A22"}:
        p = tx.run_dir / "scoring-summary.json"
        pl = json.loads(p.read_text())
        pl["item_count" if attack == "A2" else "raw_manifest_hash"] = 0 if attack == "A2" else "0" * 64
        p.write_text(json.dumps(pl)); reseal(p)
        if attack == "A22":
            with pytest.raises(TransactionError, match="manifest"):
                tx.execute_gate_evaluation()
        else:
            assert all(g.status.value != "PASS" for g in tx.execute_gate_evaluation())
        return
    if attack == "A27":
        tx.gate_config_path.write_text(tx.gate_config_path.read_text()+" ")
        with pytest.raises(TransactionError, match="freeze|config"):
            tx.execute_gate_evaluation()
        return
    cfg = json.loads(tx.gate_config_path.read_text())
    fake = {gid: {k:v["value"] for k,v in d["requirements"].items()} for gid,d in cfg["gates"].items()}
    gates = tx.execute_gate_evaluation(fake if attack == "A10" else None,
        {gid:["contract-freeze.json"] for gid in fake} if attack == "A11" else None)
    if attack in {"A10", "A11"}:
        assert all(g.status.value != "PASS" and not g.evidence and not g.observed for g in gates)
        return
    if attack in {"A25", "A26"}:
        arg = {"final_verdict": "PROFILE_B_PASS_NATIVE"} if attack == "A25" else {"lifecycle_valid": True}
        with pytest.raises(TypeError):
            tx.execute_verdict_derivation(**arg)
        assert tx.execute_verdict_derivation().status != VerdictStatus.PROFILE_B_PASS_NATIVE
        return
    tx.execute_verdict_derivation()
    if attack == "A3":
        with pytest.raises(TransactionError, match="empty evidence"):
            tx.execute_evidence_index([])
        return
    if attack == "A29":
        with pytest.raises(TransactionError, match="duplicate"):
            tx.execute_evidence_index([record(tx), {**record(tx), "source_run_id": "RUN-other"}])
        return
    if attack == "A23":
        tx.execute_evidence_index([record(tx)])
        (tx.run_dir / "observations.jsonl").write_text(json.dumps({"run_id": tx.run_id})+"\n"+json.dumps({"run_id":"RUN-other"}))
        with pytest.raises(TransactionError, match="run-id consistency"):
            tx.execute_run_id_consistency()
        return
    pytest.fail(f"attack not implemented: {attack}")
