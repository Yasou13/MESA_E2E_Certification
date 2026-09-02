"""
Deterministic Retrieval Scorer for Profile B.
Evaluates single-hop, relational, and negative retrieval against source ground truth.
"""

from typing import Any
from harness.models import GroundTruthItem, RetrievalScore
from harness.identity import IdentityMap

def score_retrieval(
    gt: GroundTruthItem,
    retrieved_results: list[dict[str, Any]],
    identity_map: IdentityMap,
    is_infrastructure_error: bool = False
) -> RetrievalScore:
    """Score retrieval results deterministically."""
    if is_infrastructure_error:
        return RetrievalScore(
            query_id=gt.query_id,
            query_class=gt.query_class,
            is_answerable=gt.is_answerable,
            status="INFRASTRUCTURE_ERROR",
            rank=None,
            recall_at_1=0.0,
            recall_at_5=0.0,
            mrr=0.0,
            group_coverage_at_5=0.0,
            complete_evidence_at_5=0.0,
            normalized_retrieved_chunk_ids=[],
            matching_chunk_ids=[]
        )

    # 1. Normalize retrieved chunk IDs to source IDs
    normalized_chunks_by_rank: list[tuple[int, str]] = []
    all_normalized_chunk_ids: list[str] = []
    for idx, res in enumerate(retrieved_results[:5]):
        rank = idx + 1
        raw_ids: list[str] = []
        if res.get("chunk_id"):
            raw_ids.append(res["chunk_id"])
        elif res.get("id"):
            raw_ids.append(res["id"])
        if "provenance" in res:
            if isinstance(res["provenance"], dict) and res["provenance"].get("chunk_id"):
                raw_ids.append(res["provenance"]["chunk_id"])
            elif isinstance(res["provenance"], list):
                for p in res["provenance"]:
                    if isinstance(p, dict) and p.get("chunk_id"):
                        raw_ids.append(p["chunk_id"])
        for raw_id in raw_ids:
            norm_id = identity_map.resolve_source_chunk_id(raw_id)
            if norm_id:
                normalized_chunks_by_rank.append((rank, norm_id))
                if norm_id not in all_normalized_chunk_ids:
                    all_normalized_chunk_ids.append(norm_id)

    # NO_ANSWER queries are not scored for hit/recall in retrieval lane
    if not gt.is_answerable or gt.query_class == "NO_ANSWER":
        return RetrievalScore(
            query_id=gt.query_id,
            query_class=gt.query_class,
            is_answerable=False,
            status="NO_ANSWER_EVALUATED_IN_ANSWER_STAGE",
            rank=None,
            recall_at_1=0.0,
            recall_at_5=0.0,
            mrr=0.0,
            group_coverage_at_5=1.0,
            complete_evidence_at_5=1.0,
            normalized_retrieved_chunk_ids=all_normalized_chunk_ids,
            matching_chunk_ids=[]
        )

    # 2. Relational Query Scoring
    if gt.query_class == "RELATIONAL" and gt.evidence_groups:
        covered_groups = set()
        matched_chunks = []
        first_hit_rank = None

        for group in gt.evidence_groups:
            group_acceptable = set(group.acceptable_source_chunk_ids)
            for rank, chunk_id in normalized_chunks_by_rank:
                if chunk_id in group_acceptable:
                    covered_groups.add(group.group_id)
                    matched_chunks.append(chunk_id)
                    if first_hit_rank is None or rank < first_hit_rank:
                        first_hit_rank = rank

        total_groups = len(gt.evidence_groups)
        group_coverage = len(covered_groups) / total_groups if total_groups > 0 else 1.0
        complete_evidence = 1.0 if len(covered_groups) == total_groups else 0.0
        
        hit_rank = first_hit_rank
        r1 = 1.0 if hit_rank == 1 else 0.0
        r5 = 1.0 if hit_rank is not None and hit_rank <= 5 else 0.0
        mrr = 1.0 / hit_rank if hit_rank is not None else 0.0

        return RetrievalScore(
            query_id=gt.query_id,
            query_class=gt.query_class,
            is_answerable=True,
            status="HIT" if complete_evidence == 1.0 else ("PARTIAL" if group_coverage > 0 else "MISS"),
            rank=hit_rank,
            recall_at_1=r1,
            recall_at_5=r5,
            mrr=mrr,
            group_coverage_at_5=group_coverage,
            complete_evidence_at_5=complete_evidence,
            normalized_retrieved_chunk_ids=all_normalized_chunk_ids,
            matching_chunk_ids=list(set(matched_chunks))
        )

    # 3. Single-hop / Standard Scoring
    expected_ids = set(gt.expected_source_chunk_ids)
    first_hit_rank = None
    matched_chunks = []

    for rank, chunk_id in normalized_chunks_by_rank:
        if chunk_id in expected_ids:
            if first_hit_rank is None:
                first_hit_rank = rank
            matched_chunks.append(chunk_id)

    if first_hit_rank is not None:
        return RetrievalScore(
            query_id=gt.query_id,
            query_class=gt.query_class,
            is_answerable=True,
            status="HIT",
            rank=first_hit_rank,
            recall_at_1=1.0 if first_hit_rank == 1 else 0.0,
            recall_at_5=1.0 if first_hit_rank <= 5 else 0.0,
            mrr=1.0 / first_hit_rank,
            group_coverage_at_5=1.0,
            complete_evidence_at_5=1.0,
            normalized_retrieved_chunk_ids=all_normalized_chunk_ids,
            matching_chunk_ids=list(set(matched_chunks))
        )

    return RetrievalScore(
        query_id=gt.query_id,
        query_class=gt.query_class,
        is_answerable=True,
        status="MISS",
        rank=None,
        recall_at_1=0.0,
        recall_at_5=0.0,
        mrr=0.0,
        group_coverage_at_5=0.0,
        complete_evidence_at_5=0.0,
        normalized_retrieved_chunk_ids=all_normalized_chunk_ids,
        matching_chunk_ids=[]
    )
