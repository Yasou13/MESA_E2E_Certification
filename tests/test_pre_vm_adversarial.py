"""Independent false-PASS attacks added during the pre-VM completion audit."""

from __future__ import annotations

import json

import pytest

from harness.finalizer import ReleaseFinalizationError, finalize_release
from tests.independent_support import placeholder_sources


def test_all_b0_b14_status_only_pass_rows_cannot_finalize(tmp_path) -> None:
    sources = placeholder_sources(tmp_path)
    gate_payload = json.loads(sources["gate-results.json"].read_text())
    gate_payload.update(
        {
            "final_verdict": "PROFILE_B_PASS_NATIVE",
            "mandatory_gate_ids": [f"B{index}" for index in range(15)],
            "gates": [
                {
                    "schema_version": "1.0",
                    "gate_id": f"B{index}",
                    "hard": True,
                    "execution_status": "COMPLETED",
                    "status": "PASS",
                    "required": {},
                    "observed": {},
                    "reason": "forged status-only pass",
                    "evidence": [],
                }
                for index in range(15)
            ],
        }
    )
    sources["gate-results.json"].write_text(json.dumps(gate_payload))

    with pytest.raises(
        ReleaseFinalizationError, match="requirements|authoritative evidence"
    ):
        finalize_release(
            run_id="RUN-independent",
            sources=sources,
            release_root=tmp_path / "release",
        )
