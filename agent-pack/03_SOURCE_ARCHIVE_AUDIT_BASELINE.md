> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 03 — SOURCE ARCHIVE AUDIT BASELINE

This is a static audit of the two source archives supplied when v3.0 of this pack was created. **These findings are a baseline to revalidate, not the live certification result.**

## Source snapshot identity

### MESA archive

```text
Archive: MESA-main (14).zip
SHA-256: dce108b7263de36ecc14d680adb79ee659992cb18f69d020146f252526fd4423
Archive comment / source revision: fde3633627501937de8cae9be50b3b2438cf5687
Project version: 0.7.1
```

### MESA_Data archive

```text
Archive: MESA_Data-main (32).zip
SHA-256: 4b1dbc852522f53ff09ee7a15081c8d7fa048d2d28043c2e750d8264476ed18b
Archive comment / source revision: cd54075a33e66086df2a5f521676aa497e420071
Project version: 0.1.0
```

## MESA findings

### Positive findings to revalidate

- Docker image build includes both `ml` and `adapters` extras; the runtime wheel is installed with `[ml,adapters]`, so the OpenAI SDK should exist in the production image.
- Current extraction code contains `MESA_EXTRACTION_MAX_TOKENS` with archive default 4096.
- Extraction prompts demand the `{"facts": [...]}` root structure.
- Fact extraction rejects unsafe bare-list coercion instead of silently turning it into an empty `facts` list.
- Provider-failure handling unwraps nested/Tenacity exceptions and recognizes OpenAI/httpx timeout/connection/rate-limit classes.
- Nemotron-specific identity logic is present in the embedding service.
- V4 search includes vector, lexical/BM25, assertion and graph lanes; graph retrieval calls a real Kùzu graph provider and public results can expose graph provenance.

### P0/P1 preflight finding: Compose configuration parity

The inspected `docker-compose.v4.yml` propagated several external-provider variables but omitted Profile B-critical values observed in config/code, including:

```text
MESA_EMBEDDING_VERSION
MESA_EMBEDDING_BASE_URL
MESA_EMBEDDING_API_KEY
MESA_EXTRACTION_MAX_TOKENS
```

`MESA_EXTRACTION_LANG` also was not explicitly propagated although the archive default was Turkish. A direct `uv run python` probe can therefore pass while the actual Docker runtime uses different/default identity/settings. Profile B must treat **host-vs-container provider/config parity as a hard pre-benchmark gate**.

### Observed MESA V4 HTTP contract

The archive exposed:

```text
GET  /health
POST /v4/catalog/workspaces
POST /v4/catalog/datasets
POST /v4/catalog/documents
POST /v4/catalog/revisions
POST /v4/catalog/source-chunks
POST /v4/sessions/start
POST /v4/memory/insert
POST /v4/memory/search
GET  /v4/mutations/{mutation_id}
GET  /v4/sessions/{session_id}/context
```

Important: `/v4/catalog/source-chunks` is a catalog/provenance endpoint; `/v4/memory/insert` is the cognitive async ingestion path used for extraction/projection/retrieval and returns a mutation workflow.

Archive `V4MemoryInsertRequest` required:

```text
session_id
dataset_id
document_id
revision_id
chunk_id
title
source_ref
content
revision_number
chunk_ordinal
finalize_revision
metadata
idempotency_key (optional, JSON body)
```

The session is authenticated/principal-bound and requires dataset/session authorization. The archive's admin CLI supports API-key issuance plus scope roles and agent permissions.

## MESA_Data findings

### Positive findings to revalidate

- Dedicated encoding decoder supports HTML charset detection, Windows-1254/cp1254 and ISO-8859-9 without lossy `errors="ignore"` source decoding.
- Mojibake detection exists.
- Unit/integration coverage exists for cp1254 and pipeline/web rendering.
- Version-level bulk approve/reject and side-by-side raw vs canonical review are present.
- Parsing coverage/data-loss logic exists; archive thresholds included a 30% minimum legislation coverage and review logic for large unexplained gaps. Profile B must validate behavior on the real selected corpus rather than adding another parallel quality system.
- Publisher has immutable release input, deterministic chunk planning, content hashing, stable idempotency-key generation, delivery ledger/state tracking and cross-release committed-chunk deduplication.
- README explicitly distinguishes real MESA delivery from local development staging.

### P0 preflight finding: native publisher contract mismatch

The inspected MESA_Data publisher's generic `publish_source_chunk()` built a payload containing fields such as:

```text
tenant_id, workspace_id, dataset_id, agent_id,
document_id, version_id, chunk_id, chunk_type,
title, char_start, char_end, ordinal,
content, content_hash, metadata
```

It sent the idempotency key in an `Idempotency-Key` header to a configurable publish path. Tests/examples commonly mocked:

```text
GET  /v4/health
POST /v4/sources/chunks
GET  /v4/mutations/{mutation_id}
```

Those mocked health/publish routes were not present in the supplied MESA archive. The supplied MESA cognitive ingestion route was `/v4/memory/insert`, required `session_id`, `revision_id`, `source_ref`, `chunk_ordinal`, etc., and accepted the idempotency key in the JSON body.

Therefore the two supplied archives did **not statically demonstrate native interoperability**. Mocked publisher E2E tests are insufficient. The live certification agent must test this first and, if the mismatch still exists, repair the native cross-repo contract before corpus benchmarking.

## Required response to archive findings

The agent must:

1. compare live `HEAD` against these findings;
2. record `CONFIRMED`, `ALREADY_FIXED`, or `CHANGED_CONTRACT` for each;
3. never patch an issue that no longer exists;
4. if confirmed, create a minimal reproducer and regression test, repair it on the certification branch, then invalidate/restart the run;
5. update run documentation with the exact live code path, not this archive's stale line numbers.

