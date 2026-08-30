> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 10 — CORPUS DESIGN

## Target

Build a legal corpus large enough to exercise real retrieval without turning Profile B into a crawling-scale benchmark.

```text
Target selected documents: 60
Hard minimum eligible selected documents: 50
Maximum for this profile: 80 unless user explicitly changes the profile before run start
```

If fewer than 50 official documents survive quality gates, stop `BLOCKED_DATASET`/Profile B FAIL as appropriate. Do not lower quality gates or add unapproved sources after seeing benchmark needs.

## Deterministic selection

Selection must occur before MESA ingestion and before MESA retrieval is visible to the ground-truth authoring process.

Create a candidate manifest with source/document/version IDs, source class, legal type, acquisition timestamp and quality status. Sort deterministically by a documented key, then select with predefined diversity constraints.

Recommended diversity:

- core seed legislation (where official/current/eligible);
- recent official Resmî Gazete legislation/regulatory documents from a fixed acquisition window;
- multiple legal subject areas;
- enough shared legal entities/citations/concepts to support 10 relational questions;
- documents with representative encoding/HTML/PDF shapes.

Do not choose documents because MESA retrieves them well.

## DEV/TEST evidence partition

Before authoring questions, partition selected evidence deterministically:

- **DEV evidence:** about 8 documents, used for 12 non-scored tuning/smoke queries;
- **TEST evidence:** remaining documents, used for all 80 scored queries.

A TEST question must not have its primary expected evidence in a DEV-only document. If one legal proposition legitimately spans both, reassign documents/query before freeze.

## Corpus manifest fields

At minimum:

```text
source_name
source_url / official locator
document_id
version_id
title
document_type
publication/effective metadata if available
raw_sha256
canonical_sha256
quality_status
encoding
coverage_ratio
selected_partition = DEV|TEST
planned_chunk_count
release_id
```

Hash the final corpus manifest before GT generation.

## No hidden enrichment

MESA receives the MESA_Data canonical/planned chunk content and provenance. Do not manually rewrite chunks, add explanatory synthetic paragraphs, or insert answer text solely to increase retrieval scores.

