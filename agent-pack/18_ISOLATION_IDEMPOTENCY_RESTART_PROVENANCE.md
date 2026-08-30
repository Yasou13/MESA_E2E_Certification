> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 18 — ISOLATION, IDEMPOTENCY, RESTART AND PROVENANCE

## Restart persistence

After full native ingestion reaches COMMITTED:

1. capture baseline searchable query/result/provenance;
2. cleanly restart MESA service/container without deleting volumes;
3. wait for health/capability;
4. repeat fixed persistence probes;
5. require expected committed content and provenance to remain available.

Do not confuse a process restart with a fresh-run storage reset.

## Idempotency

Test at two levels:

### Same request / same key

Retry identical chunk ingestion/delivery. Expect a legitimate duplicate/already-committed/skipped semantic outcome and no second logical source chunk/fact set.

### Response-loss style retry

Where the native publisher supports it, simulate or test a request whose response is lost after remote acceptance, then reconcile/poll/retry with the same stable idempotency identity. Do not simulate by corrupting production storage.

Compare counts before/after.

## Provenance chain

For sampled queries prove:

```text
official URL/raw SHA
→ MESA_Data document/version
→ canonical content hash
→ SourceChunk ID/content hash
→ native publisher ledger item/idempotency key
→ MESA mutation ID/COMMITTED
→ MESA document/revision/chunk/source_ref
→ retrieval result provenance
→ answer evidence_chunk_ids
```

At least 10 sampled answerable queries plus every REL query should have a machine-verifiable chain.

## Isolation / ACL hard gate

Create two distinct certification scopes, e.g. Tenant A and Tenant B, with separate principals/keys or at least principal bindings that exercise actual RBAC. Insert unique marker data in each through authorized paths.

From Tenant A credentials/session, negative tests must prove it cannot:

- search Tenant B data;
- fetch/use Tenant B context;
- list/read Tenant B workspaces/datasets/documents/revisions/source-chunk catalog where the API provides corresponding scoped reads;
- access Tenant B mutation status/session if current authorization is designed to hide/deny it.

Repeat symmetric checks where practical.

Expected responses may be `403`, `404`, filtered empty listing, or another documented safe behavior. The invariant is **zero data/provenance leakage**. Any Tenant B content, identifiers that should be hidden, or source text returned to Tenant A is a hard fail.

Do not weaken roles or share one super-admin key for the isolation test.

