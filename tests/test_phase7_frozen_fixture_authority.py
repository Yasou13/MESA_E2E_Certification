"""Fail-closed tests for official frozen Phase 7 fixture authority."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from harness.identity import IdentityMap
from harness.qualification_runner import (
    QualificationRunnerError,
    _load_frozen_scope_authority,
)
from harness.scope_collector import (
    collect_phase7_scope_isolation,
)
from tests.scope_fixture_support import (
    build_synthetic_scope_test_matrix,
    frozen_scope_fixture_authority,
)


def _authority(tmp_path: Path) -> tuple[dict, IdentityMap]:
    scope_authority, rows = frozen_scope_fixture_authority()
    rows.append(
        {
            "mesa_chunk_id": "allowed-chunk",
            "source_chunk_id": "allowed-source",
            "content_hash": "5" * 64,
            "delivery_state": "COMMITTED",
            "document_id": "doc-1",
            "remote_mutation_id": "allowed-mutation",
            "version_id": "allowed-revision",
        }
    )
    identity_path = tmp_path / "identity-map.jsonl"
    identity_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    identity_map = IdentityMap()
    identity_map.load_from_file(identity_path)
    freeze = {
        "runtime_identities": {
            "qualification_scope": {
                "tenant_id": "tenant-auth",
                "workspace_id": "workspace-auth",
                "dataset_ids": ["dataset-auth"],
                "agent_id": "agent-auth",
                "expected_principal": "principal-user-1",
            },
            "scope_test_authority": scope_authority,
        }
    }
    return freeze, identity_map


def _rejects(
    tmp_path: Path, mutate, match: str = "BLOCKED_BY_QUALIFICATION_SCOPE_FIXTURE"
) -> None:
    freeze, identity_map = _authority(tmp_path)
    mutate(freeze["runtime_identities"]["scope_test_authority"])
    with pytest.raises(QualificationRunnerError, match=match):
        _load_frozen_scope_authority(freeze, identity_map)


def test_identity_only_scope_authority_cannot_trigger_synthetic_defaults(
    tmp_path: Path,
) -> None:
    freeze, identity_map = _authority(tmp_path)
    authority = freeze["runtime_identities"]["scope_test_authority"]
    freeze["runtime_identities"]["scope_test_authority"] = {
        key: authority[key]
        for key in ("forbidden_tenant", "forbidden_dataset", "forbidden_agent")
    }
    with pytest.raises(
        QualificationRunnerError,
        match="BLOCKED_BY_QUALIFICATION_SCOPE_FIXTURE.*missing fields",
    ):
        _load_frozen_scope_authority(freeze, identity_map)


def test_missing_authorized_document_fails_closed(tmp_path: Path) -> None:
    _rejects(tmp_path, lambda authority: authority.pop("authorized_document"))


def test_missing_case_fixture_fails_closed(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        lambda authority: authority["case_evidence_fixtures"].pop(
            "inactive_status_search"
        ),
    )


def test_empty_required_fixture_list_fails_closed(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        lambda authority: authority["case_evidence_fixtures"].update(
            {"inactive_status_search": []}
        ),
    )


def test_unknown_evidence_id_fails_closed(tmp_path: Path) -> None:
    def mutate(authority: dict) -> None:
        fixture_id = authority["case_evidence_fixtures"]["inactive_status_search"][0]
        authority["corpus_fixtures"][fixture_id]["source_chunk_id"] = "unknown-source"

    _rejects(tmp_path, mutate, match="unknown frozen corpus identity")


def test_evidence_id_absent_from_identity_authority_fails_closed(
    tmp_path: Path,
) -> None:
    def mutate(authority: dict) -> None:
        old_id = authority["case_evidence_fixtures"]["inactive_status_search"][0]
        new_id = "scope-ev-not-in-identity-authority"
        authority["case_evidence_fixtures"]["inactive_status_search"] = [new_id]
        authority["corpus_fixtures"][new_id] = authority["corpus_fixtures"].pop(old_id)

    _rejects(tmp_path, mutate, match="absent from the frozen identity authority")


@pytest.mark.parametrize(
    ("case_id", "field", "value", "message"),
    [
        ("inactive_status_search", "status", "ACTIVE", "not inactive"),
        ("cross_tenant_search", "tenant_id", "tenant-auth", "forbidden tenant"),
        ("stale_version_search", "is_current", True, "not marked non-current"),
    ],
)
def test_wrong_semantic_fixture_fails_closed(
    tmp_path: Path, case_id: str, field: str, value: object, message: str
) -> None:
    freeze, identity_map = _authority(tmp_path)
    authority = freeze["runtime_identities"]["scope_test_authority"]
    fixture_id = authority["case_evidence_fixtures"][case_id][0]
    record = authority["corpus_fixtures"][fixture_id]
    record[field] = value
    source_chunk_id = record["source_chunk_id"]
    identity_map._rows_by_source[source_chunk_id] = [  # noqa: SLF001
        row.model_copy(update={field: value})
        for row in identity_map._rows_by_source[source_chunk_id]  # noqa: SLF001
    ]
    with pytest.raises(QualificationRunnerError, match=message):
        _load_frozen_scope_authority(freeze, identity_map)


def test_temporal_fixture_valid_at_probe_boundary_fails_closed(tmp_path: Path) -> None:
    freeze, identity_map = _authority(tmp_path)
    authority = freeze["runtime_identities"]["scope_test_authority"]
    fixture_id = authority["case_evidence_fixtures"]["effective_date_boundary_search"][
        0
    ]
    record = authority["corpus_fixtures"][fixture_id]
    dates = {
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_to": "2026-12-31T23:59:59Z",
    }
    record.update(dates)
    source_chunk_id = record["source_chunk_id"]
    identity_map._rows_by_source[source_chunk_id] = [  # noqa: SLF001
        row.model_copy(update=dates)
        for row in identity_map._rows_by_source[source_chunk_id]  # noqa: SLF001
    ]
    with pytest.raises(QualificationRunnerError, match="valid at the Phase 7 boundary"):
        _load_frozen_scope_authority(freeze, identity_map)


def test_unknown_case_name_fails_closed(tmp_path: Path) -> None:
    def mutate(authority: dict) -> None:
        authority["case_evidence_fixtures"]["invented_case"] = ["invented-fixture"]
        authority["corpus_fixtures"]["invented-fixture"] = deepcopy(
            next(iter(authority["corpus_fixtures"].values()))
        )

    _rejects(tmp_path, mutate, match="supported cases")


def test_synthetic_unit_fixture_cannot_reach_official_collector(
    tmp_path: Path,
) -> None:
    native_session = "sess_native_fixture_test"
    cases = [
        case.model_copy(
            update={
                "request_payload": {
                    **case.request_payload,
                    **(
                        {"session_id": native_session}
                        if "session_id" in case.request_payload
                        else {}
                    ),
                }
            }
        )
        for case in build_synthetic_scope_test_matrix()
    ]
    with pytest.raises(RuntimeError, match="frozen fixture authority hash"):
        collect_phase7_scope_isolation(
            run_id="RUN-SYNTHETIC-REJECT",
            run_dir=tmp_path / "RUN-SYNTHETIC-REJECT",
            mesa_sha="a" * 40,
            test_cases=cases,
            mesa_executor=lambda _case: {},
            execution_session=object(),  # type: ignore[arg-type]
            session_id=native_session,
            fixture_authority_hash="0" * 64,
        )


def test_collector_never_invents_default_phase7_cases(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="requires explicit test cases"):
        collect_phase7_scope_isolation(
            run_id="RUN-NO-DEFAULTS",
            run_dir=tmp_path / "RUN-NO-DEFAULTS",
            mesa_sha="a" * 40,
            mesa_executor=lambda _case: {},
        )
