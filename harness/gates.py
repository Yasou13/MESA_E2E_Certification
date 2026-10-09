"""Machine-readable threshold gate evaluation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.models import ExecutionStatus, GateResult, GateStatus
from harness.metric_producers import (
    PRODUCTION_METRIC_PRODUCERS as _PRODUCTION_METRIC_PRODUCER_REGISTRY,
)


PROFILE_B_GATE_IDS = frozenset(f"B{i}" for i in range(15))
# Public completeness view used by verdict/finalizer validation. The mapping
# itself lives with the producer implementations so registration cannot drift
# away from executable production code.
PRODUCTION_METRIC_PRODUCERS: frozenset[str] = frozenset(
    _PRODUCTION_METRIC_PRODUCER_REGISTRY
)


class MetricRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal["gte", "lte", "eq"]
    value: float | int | bool


class GateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    name: str | None = None
    hard: bool = True
    requirements: dict[str, MetricRequirement] = Field(default_factory=dict)
    wait_for_mesa: bool = False
    unresolved_methodology: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def validate_gate(self) -> "GateDefinition":
        if (
            not self.wait_for_mesa
            and not self.unresolved_methodology
            and not self.requirements
        ):
            raise ValueError(
                f"Gate {self.gate_id} must have requirements unless wait_for_mesa or unresolved_methodology is set"
            )
        return self


class ResourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ram_min_gib: int = Field(gt=0)
    ram_recommended_gib: int = Field(gt=0)
    disk_min_gib: int = Field(gt=0)

    @model_validator(mode="after")
    def recommendation_must_not_weaken_minimum(self) -> "ResourceContract":
        if self.ram_recommended_gib < self.ram_min_gib:
            raise ValueError("recommended RAM cannot be below the hard minimum")
        return self


class RetrievalContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    top_k: int = Field(gt=0)
    answer_context_policy: Literal["sealed_retrieval_top_k"]


class EmbeddingProviderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimension: int = Field(gt=0)
    endpoint: str | None = None
    resolved_digest: str | None = None
    normalization: str | None = None
    document_input_type: str | None = None
    query_input_type: str | None = None


class ExtractionProviderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    language: str = Field(min_length=1)
    minimum_max_tokens: int = Field(gt=0)
    endpoint: str | None = None
    resolved_digest: str | None = None
    quantization: str | None = None


class AnswerProviderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    endpoint: str | None = None
    resolved_digest: str | None = None
    quantization: str | None = None


class ProviderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    embedding: EmbeddingProviderContract
    extraction: ExtractionProviderContract
    answer: AnswerProviderContract


class OfficialProfileBContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resources: ResourceContract
    retrieval: RetrievalContract
    providers: ProviderContract


class GateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    official_contract: OfficialProfileBContract
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
        missing_mandatory = set(self.mandatory_gate_ids) - set(self.gates.keys())
        if missing_mandatory:
            raise ValueError(
                f"GATE_REGISTRY_INCOMPLETE: missing mandatory gate definitions: {sorted(missing_mandatory)}"
            )
        b1 = self.gates.get("B1")
        if b1 is not None:
            expected_resources = {
                "ram_min_gb": self.official_contract.resources.ram_min_gib,
                "disk_min_gb": self.official_contract.resources.disk_min_gib,
            }
            for metric, expected in expected_resources.items():
                requirement = b1.requirements.get(metric)
                if (
                    requirement is None
                    or requirement.operator != "gte"
                    or requirement.value != expected
                ):
                    raise ValueError(
                        f"B1 {metric} must derive from official_contract.resources"
                    )
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
    if definition.wait_for_mesa:
        return GateResult(
            gate_id=definition.gate_id,
            hard=definition.hard,
            execution_status=execution_status,
            status=GateStatus.BLOCKED,
            required=required,
            observed=dict(sorted(observed.items())),
            reason="WAIT_FOR_MESA",
            evidence=evidence,
        )
    if definition.unresolved_methodology:
        return GateResult(
            gate_id=definition.gate_id,
            hard=definition.hard,
            execution_status=execution_status,
            status=GateStatus.UNVERIFIED,
            required=required,
            observed=dict(sorted(observed.items())),
            reason="UNRESOLVED_METHODOLOGY",
            evidence=evidence,
        )
    if execution_status is not ExecutionStatus.COMPLETED:
        return GateResult(
            gate_id=definition.gate_id,
            hard=definition.hard,
            execution_status=execution_status,
            status=GateStatus.FAIL,
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
            status=GateStatus.FAIL,
            required=required,
            observed=observed,
            reason="missing_gate_evidence",
            evidence=[],
        )
    _METRIC_ALIASES: dict[str, str] = {
        "embedding_dim_verified": "nemotron_dim_verified",
        "nemotron_dim_verified": "embedding_dim_verified",
        "completion_verified": "gpt_oss_completion_verified",
        "gpt_oss_completion_verified": "completion_verified",
    }
    resolved_observed = dict(observed)
    for target_key, alias_key in _METRIC_ALIASES.items():
        if (
            target_key in definition.requirements
            and target_key not in resolved_observed
            and alias_key in resolved_observed
        ):
            resolved_observed[target_key] = resolved_observed[alias_key]

    missing = sorted(set(definition.requirements) - resolved_observed.keys())
    if missing:
        return GateResult(
            gate_id=definition.gate_id,
            hard=definition.hard,
            execution_status=execution_status,
            status=GateStatus.FAIL,
            required=required,
            observed=resolved_observed,
            reason=f"missing_observed_metrics:{','.join(missing)}",
            evidence=evidence,
        )
    failed = sorted(
        metric
        for metric, requirement in definition.requirements.items()
        if not _comparison_passes(resolved_observed[metric], requirement)
    )
    return GateResult(
        gate_id=definition.gate_id,
        hard=definition.hard,
        execution_status=execution_status,
        status=GateStatus.FAIL if failed else GateStatus.PASS,
        required=required,
        observed=dict(sorted(resolved_observed.items())),
        reason=(
            f"threshold_not_met:{','.join(failed)}" if failed else "thresholds_met"
        ),
        evidence=evidence,
    )


def write_gate_result(result: GateResult, path: str | Path) -> None:
    serialized = (
        json.dumps(
            result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n"
    )
    Path(path).write_text(serialized, encoding="utf-8", newline="\n")
