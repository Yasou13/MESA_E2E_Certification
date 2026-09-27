# Verified MESA contract map

Reference checkout: `/home/yasin/Desktop/MESA` at
`194f7b2b439ae6b9bc0f420a42a98eff1f4db2d0` (`main`, equal to the inspected
`origin/main`). The checkout was used read-only; its pre-existing untracked
prompt file was not modified.

| Area | Native MESA source | E2E consumer | Result |
|---|---|---|---|
| API identity | `V4CapabilityResponse.api_version` | `normalize_search_response`, `normalize_context_response` | `v4` + frozen full MESA SHA required |
| Retrieval | `V4SearchRequest`, `POST /v4/memory/search`, `MemoryDAO.search_v4_memory` | `mesa_adapters.py`, `official_scoring.py` | Implemented |
| Exact context | `ContextBuilder.build_context`, `GET /v4/sessions/{session_id}/context` | `normalize_context_response`, `answer_execution.py` | Implemented; E2E owns final answer call |
| Scope proof | Session authorization and internal pre-rank SQL filters | Phase 7 adapter; B9/B10 producers | Blocked: public candidate agent/principal and pre-rank audit identity absent |
| Graph proof | Graph provenance in `search_v4_memory` | Graph adapter and B11 producer | Blocked: stable path ID and native paired ON/OFF switch absent |

No MESA class, field, method or endpoint name in the adapters was inferred from
documentation alone; each was checked in the source above.

