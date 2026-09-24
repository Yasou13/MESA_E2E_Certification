from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.finalizer import (
    REQUIRED_RELEASE_FILES,
    ReleaseFinalizationError,
    finalize_release,
    verify_release_bundle,
)
from harness.operations import (
    HealthPhase,
    OperationalStatus,
    ResourcePressureEvent,
    ResourceSample,
    RuntimeLock,
    ServiceHealth,
    capture_health_snapshot,
    evaluate_resource_status,
    write_health_snapshot,
    write_resource_artifacts,
    write_runtime_lock,
)


RUN_ID = "RUN-20260924T120000Z-test"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def test_health_snapshot_is_explicitly_healthy_unhealthy_or_unverified(
    tmp_path: Path,
) -> None:
    healthy = capture_health_snapshot(
        run_id=RUN_ID,
        phase=HealthPhase.PRE_TEST,
        timestamp_utc=NOW,
        services=[ServiceHealth(name="mesa", status=OperationalStatus.PASS, restarts=0)],
        provider_reachable=True,
        host_metrics={"memory_available_mb": 4096, "disk_free_mb": 8192},
    )
    unverified = capture_health_snapshot(
        run_id=RUN_ID,
        phase=HealthPhase.POST_TEST,
        timestamp_utc=NOW,
        services=[],
        provider_reachable=None,
        host_metrics={},
    )

    assert healthy.status is OperationalStatus.PASS
    assert unverified.status is OperationalStatus.UNVERIFIED
    path = tmp_path / "health-pre-test.json"
    write_health_snapshot(healthy, path)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "PASS"


def test_resource_oom_or_restart_fails_and_artifacts_are_written(
    tmp_path: Path,
) -> None:
    sample = ResourceSample(
        run_id=RUN_ID,
        timestamp_utc=NOW,
        host_available_ram_mb=2048,
        mesa_rss_mb=1024,
        swap_used_mb=0,
        disk_used_mb=100,
        provider_requests=1,
        provider_retries=0,
        provider_timeouts=0,
        container_restart_count=1,
        oom_killed_count=0,
    )
    event = ResourcePressureEvent(
        run_id=RUN_ID,
        timestamp_utc=NOW,
        event_type="SERVICE_RESTART",
        severity="CRITICAL",
        observed={"container_restart_count": 1},
        action="abort certification",
    )

    status = evaluate_resource_status([sample], [event])
    telemetry, events = write_resource_artifacts([sample], [event], tmp_path)

    assert status["status"] == "FAIL"
    assert telemetry.name == "resource-telemetry.jsonl"
    assert events.name == "resource-pressure-events.jsonl"
    assert evaluate_resource_status([], [])["status"] == "UNVERIFIED"


def test_runtime_lock_rejects_secret_fields_and_writes_hash_sidecar(
    tmp_path: Path,
) -> None:
    lock = RuntimeLock(
        run_id=RUN_ID,
        created_at_utc=NOW,
        mesa_repository_sha="a" * 40,
        mesa_data_repository_sha="b" * 40,
        e2e_repository_sha="c" * 40,
        runtime_identity={"image_digest": "sha256:" + "d" * 64},
        provider_identity={"model": "frozen-model", "endpoint_host": "provider"},
        config_sha256="e" * 64,
    )
    path, sidecar = write_runtime_lock(lock, tmp_path)
    assert path.name == "mesa-runtime-lock.json"
    assert sidecar.read_text(encoding="utf-8").split()[1] == path.name

    with pytest.raises(ValueError, match="secret field"):
        RuntimeLock(
            **{
                **lock.model_dump(),
                "provider_identity": {"api_key": "must-not-exist"},
            }
        )


def _release_sources(tmp_path: Path) -> dict[str, Path]:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
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
                        "gates": [{"gate_id": "B0", "status": "PASS"}],
                    }
                )
            path.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )
        result[name] = path
    return result


def test_finalizer_fails_atomically_when_artifact_missing_or_secret_present(
    tmp_path: Path,
) -> None:
    sources = _release_sources(tmp_path)
    release_root = tmp_path / "releases"
    missing = dict(sources)
    missing.pop("health-post-test.json")
    with pytest.raises(ReleaseFinalizationError, match="missing mandatory"):
        finalize_release(
            run_id=RUN_ID, sources=missing, release_root=release_root
        )
    assert not (release_root / RUN_ID).exists()

    sources["decision-summary.json"].write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": RUN_ID,
                "api_key": "secret",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseFinalizationError, match="sensitive field"):
        finalize_release(
            run_id=RUN_ID, sources=sources, release_root=release_root
        )
    assert not (release_root / RUN_ID).exists()


def test_complete_release_is_checksums_verified_and_mutation_detected(
    tmp_path: Path,
) -> None:
    sources = _release_sources(tmp_path)
    release = finalize_release(
        run_id=RUN_ID, sources=sources, release_root=tmp_path / "releases"
    )

    assert verify_release_bundle(release)["status"] == "PASS"
    assert {path.name for path in release.iterdir()} == REQUIRED_RELEASE_FILES | {
        "SHA256SUMS.txt"
    }

    (release / "answer-summary.json").write_text("{}", encoding="utf-8")
    assert verify_release_bundle(release)["status"] == "FAIL"
