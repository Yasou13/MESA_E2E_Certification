"""
Data models for Profile B Certification Harness.
"""

from typing import Any, Optional, Union
from pydantic import BaseModel, Field

class ExactSourceSpan(BaseModel):
    source_chunk_id: str
    span_id: Optional[str] = None
    exact_text: str

class RequiredFact(BaseModel):
    fact_id: str
    claim: str
    supported_by: list[ExactSourceSpan] = Field(default_factory=list)

class EvidenceGroup(BaseModel):
    group_id: str
    acceptable_source_chunk_ids: list[str] = Field(default_factory=list)

class GroundTruthItem(BaseModel):
    query_id: str
    query_class: str  # SINGLE_DIRECT, SINGLE_PARAPHRASE, RELATIONAL, TEMPORAL, CROSS_DOMAIN, COMPLEX_REASONING, NO_ANSWER
    question: str
    expected_source_chunk_ids: list[str] = Field(default_factory=list)
    evidence_groups: list[EvidenceGroup] = Field(default_factory=list)
    required_facts: list[RequiredFact] = Field(default_factory=list)
    acceptable_answer_patterns: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    is_answerable: bool = True

class MESAProvenanceItem(BaseModel):
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    source_id: Optional[str] = None
    score: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class RetrievalResultItem(BaseModel):
    rank: int
    mesa_chunk_id: str
    document_id: Optional[str] = None
    text: str = ""
    score: float = 0.0
    provenance: Optional[MESAProvenanceItem] = None

class RetrievalScore(BaseModel):
    query_id: str
    query_class: str
    is_answerable: bool
    status: str  # HIT, MISS, INFRASTRUCTURE_ERROR
    rank: Optional[int] = None
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    group_coverage_at_5: float = 1.0
    complete_evidence_at_5: float = 1.0
    normalized_retrieved_chunk_ids: list[str] = Field(default_factory=list)
    matching_chunk_ids: list[str] = Field(default_factory=list)

class AnswerResponse(BaseModel):
    answer: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False

class AnswerScore(BaseModel):
    query_id: str
    is_answerable: bool
    status: str  # PASS, FAIL, UNRESOLVED
    reasons: list[str] = Field(default_factory=list)
    grounded_pass: bool = False
    evidence_supported: bool = False
    facts_satisfied: bool = False
    forbidden_claims_absent: bool = True
