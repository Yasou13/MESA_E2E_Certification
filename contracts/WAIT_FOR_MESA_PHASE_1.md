# Phase 1 — evidence-level retrieval adapter

Status: `IMPLEMENTED`

Verified against read-only MESA checkout
`194f7b2b439ae6b9bc0f420a42a98eff1f4db2d0`.

## Native contract used

- `mesa_api/v4_router.py::V4SearchRequest` and `POST /v4/memory/search`.
- `mesa_api/v4_router.py::V4CapabilityResponse.api_version` supplies the public
  `v4` API identity. The search response itself has no schema-version field, so
  E2E requires this capability identity plus the frozen full MESA commit.
- `mesa_storage/dao.py::MemoryDAO.search_v4_memory` returns ordered results with
  first-class `candidate_id`, `evidence_id`, `assertion_id`,
  `source_chunk_id`, `document_id`, `evidence_span`, `raw_score`, `rrf_score`
  and `final_score`. It labels `matched_assertions`, `supporting_assertions` and
  broader `provenance` separately.

## E2E binding

`harness/mesa_adapters.py::normalize_search_response` validates the request and
response identity, derives rank only from response order, accepts hits only
from first-class matched evidence, bounds the evidence span, rejects unknown or
conflicting identities and preserves support/debug provenance without allowing
it to create a hit.

`harness/official_scoring.py` feeds only this normalized result into
`harness/retrieval_scorer.py` under the frozen identity map and GT/qrels.

## Verification

Covered by `tests/test_mesa_adapters.py` and
`tests/test_official_scoring_transaction.py`, including provenance-only false
hits, duplicate/conflicting IDs, malformed results, version mismatch and
official-scorer binding.
