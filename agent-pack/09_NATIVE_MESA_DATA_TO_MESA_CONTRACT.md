> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 09 — NATIVE MESA_DATA → MESA CONTRACT

This is the most important cross-repository gate discovered during pack v2 design.

## Definition of native

A native PASS means the MESA_Data product publisher/engine, after normal MESA_Data release verification and authorization, causes the current MESA product to ingest the exact planned chunks through a supported MESA V4 product contract and truthfully tracks terminal mutation state.

The following do **not** satisfy native PASS:

- a standalone certification script calling `MesaV4Client.insert()` for every chunk while bypassing MESA_Data's publisher;
- writing MESA storage directly;
- importing MESA_Data's local staging DB;
- monkey-patching HTTP responses;
- changing qrels to whatever the bridge created.

A bridge may be used only to isolate downstream behavior and can lead at most to `PROFILE_B_DIAGNOSTIC_BRIDGE_ONLY`.

## Required semantic lifecycle

The exact implementation may change, but the native product contract must semantically achieve:

```text
verified immutable MESA_Data release
→ deterministic SourceChunk list
→ authenticated MESA principal
→ authorized tenant/workspace/dataset/agent scope
→ valid active V4 session (if required by current MESA)
→ stable document/revision/chunk identity mapping
→ MESA cognitive ingestion of chunk content + source_ref
→ stable idempotency key supplied in the form MESA actually consumes
→ async mutation id captured
→ poll exact mutation endpoint/state machine
→ only terminal COMMITTED/legitimate duplicate counts as success
→ delivery ledger persists remote identity/state
→ later MESA search provenance maps back to MESA_Data source/version/chunk
```

## Archive mismatch to recheck

In the supplied snapshots, MESA_Data mocked a generic `/v4/sources/chunks` route with a payload that did not include the session/revision fields required by MESA's `/v4/memory/insert`. MESA_Data sent `Idempotency-Key` as a header while the supplied MESA cognitive insert accepted `idempotency_key` in the body. The mocked `/v4/health` also did not match MESA's `/health`.

This is a likely P0 blocker until the live repos prove otherwise.

## Repair strategy if still mismatched

Do not force a predetermined code location. Inspect both architectures and choose the smallest correct product contract. Preferred direction, if compatible with current design, is to make MESA_Data's publisher understand the real MESA V4 lifecycle rather than inventing undocumented MESA endpoints.

The repair must address all required semantics, including:

- target health/capability discovery without guessing routes;
- principal credentials and RBAC bootstrap assumptions;
- session creation/retention if required;
- document/revision/chunk/source reference mapping;
- finalization ordering for multi-chunk revisions;
- idempotency placement and payload hash stability;
- mutation state normalization;
- response-loss/retry reconciliation;
- exact provenance metadata preserving original MESA_Data IDs and content hashes.

Do not weaken MESA authentication or create a public unauthenticated bulk-ingest endpoint merely to make the publisher easier.

## Identity mapping rules

Preserve MESA_Data identity. If MESA accepts the exact `document_id`, `version_id` as `revision_id`, and `chunk_id`, use them. If current identifier validators reject any form, create a deterministic collision-resistant mapping and include original IDs in metadata/source_ref. Never use random UUIDs for source identity.

A mapping table must be emitted in run evidence:

```text
mesa_data_document_id → mesa_document_id
mesa_data_version_id  → mesa_revision_id
mesa_data_chunk_id    → mesa_chunk_id
content_hash          → MESA provenance/content identity
```

## Live compatibility regression

Mocks alone are insufficient. Before full corpus:

1. start real local MESA production-equivalent service;
2. create a tiny isolated MESA_Data release/canary through normal release code;
3. run the native publisher engine;
4. observe real HTTP status and mutation ID;
5. wait for COMMITTED;
6. search through public V4 API;
7. assert returned provenance contains the canary's exact source identity;
8. retry the same native delivery and assert no duplicate logical content/mutation side effects beyond legitimate idempotent/dedup state.

A focused mocked/unit regression may also be added to MESA_Data, but cannot replace this live gate.

## Full delivery gate

After H1, publish the frozen legal release using the exact same native code path as the canary. Compare:

```text
planned chunks
new chunks to send
already committed/skipped chunks
remote COMMITTED chunks
failed/rejected chunks
MESA-visible source chunk/provenance count
```

Unexplained mismatch = FAIL.

