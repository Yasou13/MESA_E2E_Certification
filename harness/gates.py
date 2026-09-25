"""Machine-readable threshold gate evaluation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.models import ExecutionStatus, GateResult, GateStatus


class MetricRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal["gte", "lte", "eq"]
    value: float | int | bool


class GateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    hard: bool
    requirements: dict[str, MetricRequirement] = Field(min_length=1)


class GateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    mandatory_gate_ids: list[str] = Field(min_length=1)
    gates: dict[str, GateDefinition]
    methodology_note: str

    @model_validator(mode="after")
    def gate_keys_match_ids(self) -> "GateConfig":
        mismatches = [
            key for key, definition in self.gates.items() if key != definition.gate_id
        ]
        if mismatches:
            raise ValueError(f"gate keys do not match gate_id: {mismatches}")
        if len(set(self.mandatory_gate_ids)) != len(self.mandatory_gate_ids):
            raise ValueError("mandatory_gate_ids contains duplicates")
        return self


def load_gate_config(path: str | Path) -> GateConfig:
    return GateConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _comparison_passes(observed: Any, requirement: MetricRequirement) -> bool:
    if not isinstance(observed, (int, float, bool)):
        return False
    if isinstance(observed, float) and not math.isfinite(observed):
        return False
    if requirement.operator == "gte":
        return observed >= requirement.value
    if requirement.operator == "lte":
        return observed <= requirement.value
    return observed == requirement.value


def evaluate_threshold_gate(
    definition: GateDefinition,
    observed: dict[str, Any],
    execution_status: ExecutionStatus,
    evidence: list[str],
) -> GateResult:
    required = {
        metric: requirement.model_dump(mode="json")
        for metric, requirement in sorted(definition.requirements.items())
    }
    if execution_status is not ExecutionStatus.COMPLETED:
        return GateResult(
            gate_id=definition.gate_id,
            hard=definition.hard,
            execution_status=execution_status,
            status=GateStatus.UNVERIFIED,
            required=required,
            observed=observed,
            reason="execution_not_completed",
            evidence=evidence,
        )
    if not evidence:
        return GateResult(
            gate_id=definition.gate_id,
            hard=definition.hard,
            execution_status=execution_status,
            status=GateStatus.UNVERIFIED,
            required=required,
            observed=observed,
            reason="missing_gate_evidence",
            evidence=[],
        )
    missing = sorted(set(definition.requirements) - observed.keys())
    if missing:
        return GateResult(
            gate_id=definition.gate_id,
            hard=definition.hard,
            execution_status=execution_status,
            status=GateStatus.UNVERIFIED,
            required=required,
            observed=observed,
            reason=f"missing_observed_metrics:{','.join(missing)}",
            evidence=evidence,
        )
    failed = sorted(
        metric
        for metric, requirement in definition.requirements.items()
        if not _comparison_passes(observed[metric], requirement)
    )
    return GateResult(
        gate_id=definition.gate_id,
        hard=definition.hard,
        execution_status=execution_status,
        status=GateStatus.FAIL if failed else GateStatus.PASS,
        required=required,
        observed=dict(sorted(observed.items())),
        reason=(f"threshold_not_met:{','.join(failed)}" if failed else "thresholds_met"),
        evidence=evidence,
    )


def write_gate_result(result: GateResult, path: str | Path) -> None:
    serialized = json.dumps(
        result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    Path(path).write_text(serialized, encoding="utf-8", newline="\n")
