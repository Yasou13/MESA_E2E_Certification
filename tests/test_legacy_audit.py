import hashlib
import json
from pathlib import Path

from harness.evidence import validate_run_id_consistency


REPOSITORY = Path(__file__).resolve().parents[1]
RUN_ID = "RUN-20260901T005200Z-p8b03"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def test_historical_run_bytes_match_external_audit_manifest() -> None:
    manifest = (
        REPOSITORY / "reports" / "legacy-audits" / RUN_ID / "SHA256SUMS.txt"
    )
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        expected, relative = line.split("  ", 1)
        assert _sha256(REPOSITORY / relative) == expected


def test_historical_run_id_drift_is_recorded_without_mutation() -> None:
    report = validate_run_id_consistency(REPOSITORY / "runs" / RUN_ID, RUN_ID)
    invalidation = json.loads(
        (
            REPOSITORY
            / "reports"
            / "legacy-audits"
            / RUN_ID
            / "invalidation.json"
        ).read_text(encoding="utf-8")
    )

    assert report["status"] == "RUN_ID_MISMATCH"
    assert len(report["mismatches"]) == 9
    assert invalidation["original_evidence_mutated"] is False
    assert (
        invalidation["current_interpretation"]
        == "NOT_A_VALID_PROFILE_B_V2_CERTIFICATION_RESULT"
    )
