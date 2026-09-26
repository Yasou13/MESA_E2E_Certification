from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.finalizer import (
    REQUIRED_RELEASE_FILES,
    ReleaseFinalizationError,
    finalize_release,
)

RUN_ID = "RUN-20260924T120000Z-c2"


def _make_sources(tmp_path: Path) -> dict[str, Path]:
    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for name in REQUIRED_RELEASE_FILES:
        path = source_dir / name
        if name == "final-report.md":
            path.write_text(f"# Final report\n\nRun: {RUN_ID}\n", encoding="utf-8")
        else:
            payload: dict[str, object] = {
                "schema_version": "1.0",
                "run_id": RUN_ID,
                "status": "PASS",
            }
            if name == "gate-results.json":
                payload.update(
                    {
                        "final_verdict": "PROFILE_B_PASS_NATIVE",
                        "mandatory_gate_ids": ["B10"],
                        "gates": [
                            {
                                "gate_id": "B10",
                                "hard": True,
                                "status": "PASS",
                                "requirements": {
                                    "answerable_mrr": {"operator": "gte", "value": 0.7}
                                },
                                "observed": {"answerable_mrr": 0.85},
                            }
                        ],
                    }
                )
            elif name == "contract-freeze.json":
                categories = (
                    "harness_source",
                    "scorer_source",
                    "config",
                    "ground_truth",
                    "qrels",
                    "normalization",
                    "identity_map",
                    "prompts",
                    "thresholds",
                    "runtime_identity",
                )
                payload.update(
                    {
                        "repository_shas": {
                            "MESA": "a" * 40,
                            "MESA_Data": "b" * 40,
                            "MESA_E2E_Certification": "c" * 40,
                        },
                        "materials": [
                            {"category": cat, "path": f"{cat}.txt", "sha256": "0" * 64}
                            for cat in categories
                        ],
                    }
                )
            elif name == "run_manifest.json":
                payload.update(
                    {
                        "status": "PASS_NATIVE",
                        "lifecycle_valid": True,
                    }
                )
            elif name == "determinism-manifest.json":
                payload.update(
                    {
                        "oracle_audit_status": "PASS",
                        "oracle_audit_stale": False,
                    }
                )
            path.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )
        result[name] = path
    return result


def test_c2_final_verdict_pass_with_b10_fail_fails_finalization(tmp_path: Path) -> None:
    sources = _make_sources(tmp_path)
    # Tamper gate-results so B10 is FAIL but final_verdict is PASS_NATIVE
    gate_results = json.loads(sources["gate-results.json"].read_text(encoding="utf-8"))
    gate_results["final_verdict"] = "PROFILE_B_PASS_NATIVE"
    gate_results["gates"] = [
        {
            "gate_id": "B10",
            "hard": True,
            "status": "FAIL",
            "observed": {"answerable_mrr": 0.5},
        }
    ]
    sources["gate-results.json"].write_text(
        json.dumps(gate_results, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseFinalizationError, match="B10|hard gate|tampered"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c2_final_verdict_pass_with_missing_mandatory_gate_fails(tmp_path: Path) -> None:
    sources = _make_sources(tmp_path)
    gate_results = json.loads(sources["gate-results.json"].read_text(encoding="utf-8"))
    gate_results["final_verdict"] = "PROFILE_B_PASS_NATIVE"
    gate_results["mandatory_gate_ids"] = ["B0", "B10"]
    # Only B0 is in gates list, B10 is missing
    gate_results["gates"] = [{"gate_id": "B0", "status": "PASS", "hard": True}]
    sources["gate-results.json"].write_text(
        json.dumps(gate_results, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseFinalizationError, match="mandatory gate|missing"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c2_final_verdict_pass_with_unverified_gate_fails(tmp_path: Path) -> None:
    sources = _make_sources(tmp_path)
    gate_results = json.loads(sources["gate-results.json"].read_text(encoding="utf-8"))
    gate_results["final_verdict"] = "PROFILE_B_PASS_NATIVE"
    gate_results["gates"] = [
        {
            "gate_id": "B10",
            "hard": True,
            "status": "UNVERIFIED",
        }
    ]
    sources["gate-results.json"].write_text(
        json.dumps(gate_results, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseFinalizationError, match="UNVERIFIED|hard gate|tampered"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c2_all_hard_gates_pass_but_freeze_invalid_fails(tmp_path: Path) -> None:
    sources = _make_sources(tmp_path)
    freeze_payload = json.loads(sources["contract-freeze.json"].read_text(encoding="utf-8"))
    freeze_payload["status"] = "INVALID_FREEZE"
    sources["contract-freeze.json"].write_text(
        json.dumps(freeze_payload, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseFinalizationError, match="freeze"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c2_all_gates_pass_but_oracle_audit_stale_fails(tmp_path: Path) -> None:
    sources = _make_sources(tmp_path)
    det = json.loads(sources["determinism-manifest.json"].read_text(encoding="utf-8"))
    det["oracle_audit_status"] = "STALE"
    det["oracle_audit_stale"] = True
    sources["determinism-manifest.json"].write_text(
        json.dumps(det, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseFinalizationError, match="oracle audit|stale"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c2_all_gates_pass_but_lifecycle_invalid_fails(tmp_path: Path) -> None:
    sources = _make_sources(tmp_path)
    manifest = json.loads(sources["run_manifest.json"].read_text(encoding="utf-8"))
    manifest["status"] = "INVALIDATED"
    manifest["lifecycle_valid"] = False
    sources["run_manifest.json"].write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseFinalizationError, match="lifecycle"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )


def test_c2_placeholder_conditions_cannot_certify(tmp_path: Path) -> None:
    sources = _make_sources(tmp_path)
    # A one-gate registry plus placeholder artifacts is not a valid certification.
    with pytest.raises(ReleaseFinalizationError, match="evidence index|mandatory gate|unverified"):
        finalize_release(run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases")
    assert not (tmp_path / "releases" / RUN_ID).exists()


def test_c2_serialized_final_verdict_tampered_from_fail_to_pass_detected(
    tmp_path: Path,
) -> None:
    sources = _make_sources(tmp_path)
    gate_results = json.loads(sources["gate-results.json"].read_text(encoding="utf-8"))
    # The metrics clearly fail: answerable_mrr is 0.2 < 0.7 requirement
    gate_results["final_verdict"] = "PROFILE_B_PASS_NATIVE"
    gate_results["gates"] = [
        {
            "gate_id": "B10",
            "hard": True,
            "status": "PASS",  # Falsely marked PASS!
            "requirements": {
                "answerable_mrr": {"operator": "gte", "value": 0.7}
            },
            "observed": {"answerable_mrr": 0.2},
        }
    ]
    sources["gate-results.json"].write_text(
        json.dumps(gate_results, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseFinalizationError, match="fail requirements|tampered|metric"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
        )
