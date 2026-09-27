# Phase 7 — scope/rank adversarial adapter

Status: `BLOCKED_BY_MESA_CONTRACT`

Verified against read-only MESA checkout
`194f7b2b439ae6b9bc0f420a42a98eff1f4db2d0`.

## What MESA currently proves

`POST /v4/memory/search` authorizes the session and derives tenant and agent
scope from that session. `MemoryDAO.search_v4_memory` applies tenant, dataset,
agent, status, jurisdiction and temporal filters before lane fusion/ranking.
The returned matched assertion rows expose tenant, dataset, document, revision,
chunk, status, jurisdiction and validity fields.

## Minimal missing public contract

The public ranked-candidate response does not expose:

- the candidate's `agent_id` or effective principal identity;
- a stable public pre-rank exclusion/audit identity proving that forbidden
  tenant/dataset/agent/status/temporal candidates contributed no lane rank;
- an equivalent public audit surface tying that proof to the exact query/run.

Correct internal filtering and MESA unit tests are not a certification artifact
for an external E2E consumer. E2E therefore cannot prove all required negative
scope cases or convert missing identity into zero leakage.

## E2E behavior

`harness/mesa_adapters.py::require_phase7_scope_contract` reports the precise
missing capabilities. B9 and B10 producers consume only sealed scope evidence;
without candidate scope identity and pre-rank exclusion audit they return
`BLOCKED_BY_MESA_CONTRACT`, never a synthetic leakage value.

Covered by `tests/test_mesa_adapters.py`, `tests/test_metric_producers.py` and
the official transaction integration test.
