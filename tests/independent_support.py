"""Independent production-path attacks; no imported happy-path fixtures."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from harness.artifacts import RunArtifactStore
from harness.freeze import MANDATORY_MATERIAL_CATEGORIES, create_contract_freeze
from harness.transaction import CertificationTransaction, TransactionError
from harness.models import AnswerClaim, AnswerResponse, GroundTruthItem
from harness.answer_scorer import score_answer
from harness.identity import IdentityMap
from harness.evidence import build_evidence_index, validate_run_id_consistency
from harness.finalizer import REQUIRED_RELEASE_FILES, finalize_release, ReleaseFinalizationError

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def transaction(tmp_path, request=None, response=None):
    rid = "RUN-independent"
    root = tmp_path / "materials"
    root.mkdir()
    materials = {}
    for category in sorted(MANDATORY_MATERIAL_CATEGORIES):
        p = root / (category + ".txt")
        p.write_text(category)
        materials[category] = [p]
    # Freeze the actual threshold bytes, not a placeholder bearing its category.
    cfg = root / "gates.json"
    cfg.write_bytes((ROOT / "config/profile-b-gates.json").read_bytes())
    materials["thresholds"] = [cfg]
    shas = {"MESA": "a" * 40, "MESA_Data": "b" * 40, "MESA_E2E_Certification": "c" * 40}
    f, s = create_contract_freeze(output_dir=root, run_id=rid, repository_root=root,
        repository_shas=shas, material_paths=materials, runtime_identities={"test": "independent"})
    tx = CertificationTransaction(rid, tmp_path / rid, gate_config_path=cfg)
    tx.execute_bootstrap()
    tx.execute_freeze(f, s, repository_root=root, current_repository_shas=shas)
    def raw(d):
        RunArtifactStore(d, rid).persist_raw_retrieval(query_id="Q-audit",
            request=request or {"query": "Independent query"},
            response=response or {"results": []}, transport_status=200,
            timestamp_utc=NOW, latency_ms=1, runtime_lock_sha256="0" * 64)
    tx.execute_raw_execution(raw)
    tx.execute_raw_sealing()
    return tx


def score_claims(texts):
    gt = GroundTruthItem(query_id="Q", query_class="SINGLE_DIRECT", question="Ceza?",
        expected_source_chunk_ids=["S"],
        required_facts=[{"fact_id": "f", "claim": "Ceza 5 yıldır",
            "supported_by": [{"source_chunk_id": "S", "exact_text": "Ceza 5 yıldır"}]}],
        acceptable_answer_patterns=[{"mode": "literal", "value": "Ceza 5 yıl", "fact_ids": ["f"]}])
    ids = IdentityMap()
    ids.add_mapping("M", "S")
    answer = AnswerResponse(answer=". ".join(texts), evidence_chunk_ids=["M"],
        claims=[AnswerClaim(text=t, fact_ids=["f"], evidence_chunk_ids=["M"]) for t in texts])
    return score_answer(gt, answer, ["M"], ids,
        exact_model_visible_context="Ceza 5 yıldır. Başka bir dosyada tazminat 100 milyon TL olarak belirlenmiştir.")


def placeholder_sources(tmp_path):
    run = tmp_path / "RUN-independent"
    run.mkdir()
    for name in REQUIRED_RELEASE_FILES:
        p = run / name
        if name.endswith(".md"):
            p.write_text("RUN-independent")
        else:
            pl = {"schema_version": "1.0", "run_id": run.name, "status": "PASS"}
            if name == "gate-results.json":
                pl.update(final_verdict="PROFILE_B_PASS_NATIVE", mandatory_gate_ids=["B10"],
                    gates=[{"gate_id": "B10", "hard": True, "status": "PASS"}])
            p.write_text(json.dumps(pl))
    build_evidence_index(run, run / "evidence-index.json", [{"path": "answer-summary.json",
        "producer": "independent", "phase": "test", "timestamp_utc": NOW,
        "source_run_id": run.name, "immutable": True, "sealed": True}], run_id=run.name)
    return {name: run / name for name in REQUIRED_RELEASE_FILES}


