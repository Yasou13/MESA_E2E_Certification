import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from harness.gates import (
    GateConfig,
    GateDefinition,
    evaluate_threshold_gate,
    load_gate_config,
)
from harness.models import ExecutionStatus, GateResult, GateStatus


REPOSITORY = Path(__file__).resolve().parents[1]
GATE_CONFIG_PATH = REPOSITORY / "config" / "profile-b-gates.json"


def test_mandatory_gate_missing_definition_fails_validation() -> None:
    # A config where mandatory_gate_ids has B0, but gates only has B10
    raw = {
        "schema_version": "1.0",
        "mandatory_gate_ids": ["B0", "B10"],
        "gates": {
            "B10": {
                "gate_id": "B10",
                "hard": True,
                "requirements": {
                    "answerable_mrr": {"operator": "gte", "value": 0.7}
                }
            }
        },
        "methodology_note": "test",
    }
    with pytest.raises(ValidationError, match="GATE_REGISTRY_INCOMPLETE|missing mandatory gate"):
        GateConfig.model_validate(raw)


def test_extra_diagnostic_gate_is_allowed() -> None:
    raw = {
        "schema_version": "1.0",
        "mandatory_gate_ids": ["B10"],
        "gates": {
            "B10": {
                "gate_id": "B10",
                "hard": True,
                "requirements": {
                    "answerable_mrr": {"operator": "gte", "value": 0.7}
                }
            },
            "D1": {
                "gate_id": "D1",
                "hard": False,
                "requirements": {
                    "diag_metric": {"operator": "gte", "value": 1.0}
                }
            }
        },
        "methodology_note": "diagnostic allowed",
    }
    cfg = GateConfig.model_validate(raw)
    assert "D1" in cfg.gates
    assert cfg.gates["D1"].hard is False


def test_duplicate_gate_id_fails_validation() -> None:
    raw = {
        "schema_version": "1.0",
        "mandatory_gate_ids": ["B10", "B10"],
        "gates": {
            "B10": {
                "gate_id": "B10",
                "hard": True,
                "requirements": {
                    "answerable_mrr": {"operator": "gte", "value": 0.7}
                }
            }
        },
        "methodology_note": "test",
    }
    with pytest.raises(ValidationError, match="duplicates"):
        GateConfig.model_validate(raw)


def test_evaluation_with_missing_input_produces_fail() -> None:
    defn = GateDefinition(
        gate_id="B10",
        hard=True,
        requirements={
            "answerable_mrr": {"operator": "gte", "value": 0.7},
            "answerable_recall_at_5": {"operator": "gte", "value": 0.8},
        },
    )
    # Missing answerable_recall_at_5
    result = evaluate_threshold_gate(
        defn,
        {"answerable_mrr": 0.9},
        ExecutionStatus.COMPLETED,
        ["evidence.json"],
    )
    assert result.status is GateStatus.FAIL
    assert "missing_observed_metrics" in result.reason


def test_wait_for_mesa_gate_produces_non_pass_status() -> None:
    defn = GateDefinition(
        gate_id="B_MESA",
        hard=True,
        wait_for_mesa=True,
        requirements={},
    )
    result = evaluate_threshold_gate(
        defn,
        {},
        ExecutionStatus.COMPLETED,
        ["evidence.json"],
    )
    assert result.status in {GateStatus.BLOCKED, GateStatus.UNVERIFIED}
    assert result.status is not GateStatus.PASS
    assert "WAIT_FOR_MESA" in result.reason


def test_production_profile_b_gate_config_has_all_b0_b14_executable() -> None:
    cfg = load_gate_config(GATE_CONFIG_PATH)
    expected_mandatory = [f"B{i}" for i in range(15)]
    assert cfg.mandatory_gate_ids == expected_mandatory

    # Every gate B0 to B14 must be defined and executable
    for gate_id in expected_mandatory:
        assert gate_id in cfg.gates
        defn = cfg.gates[gate_id]
        assert defn.gate_id == gate_id
        # Must evaluate to concrete GateResult
        result = evaluate_threshold_gate(
            defn,
            {},
            ExecutionStatus.COMPLETED,
            ["test_evidence.json"],
        )
        assert isinstance(result, GateResult)
        assert result.status is not GateStatus.PASS
