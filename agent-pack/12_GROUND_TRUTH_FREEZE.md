> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 12 — GROUND TRUTH AND QREL FREEZE

## Independence principle

Ground truth must be independent of the system being evaluated.

Forbidden GT inputs:

- MESA search results;
- MESA embeddings;
- MESA graph/assertions;
- MESA extraction outputs;
- GPT-OSS answers generated from MESA retrieval;
- observed benchmark scores.

Allowed GT inputs:

- approved frozen MESA_Data canonical source;
- deterministic `SourceChunk` plan from the frozen release;
- official source metadata;
- exact source evidence spans.

## Required authoring order

For each query:

```text
1. choose frozen source evidence
2. record exact evidence span(s)
3. record expected **MESA_Data source chunk ID(s)**/evidence groups
4. write required fact(s)
5. write short acceptable answer / patterns
6. write forbidden material claims
7. only then derive the natural-language question
```

This order reduces question/answer leakage and prevents retrofitting expected evidence to retrieval.

## TEST distribution

Exactly:

```text
40 SINGLE_DIRECT
20 SINGLE_PARAPHRASE
10 RELATIONAL
10 NO_ANSWER
```

Create 12 separate DEV questions first from DEV evidence. DEV questions are not part of reported TEST metrics.

## Ground-truth schema

Use JSONL or equivalent with at least:

```json
{
  "query_id": "Q001",
  "split": "TEST",
  "category": "SINGLE_DIRECT",
  "question": "...",
  "answerable": true,
  "expected_document_ids": ["..."],
  "expected_version_ids": ["..."],
  "expected_source_chunk_ids": ["..."],
  "evidence_groups": [["source-chunk-a"], ["source-chunk-b", "source-chunk-c"]],
  "evidence_spans": [{"source_chunk_id":"...","text":"exact substring"}],
  "required_facts": ["..."],
  "acceptable_answer_patterns": ["..."],
  "forbidden_claims": ["..."],
  "expected_answer": "...",
  "graph_expectation": "none|helpful|required",
  "source_notes": ""
}
```

For SINGLE queries there is normally one evidence group. For RELATIONAL queries, define two or more groups and scoring requires all groups to appear for complete-evidence@5.

For NO_ANSWER:

```text
answerable=false
expected_source_chunk_ids=[]
required_facts=[]
expected_answer="YETERSİZ KANIT"
```

A NO_ANSWER question must be plausible but not answerable from the selected frozen corpus. Verify this only from source/canonical indexes, not from MESA search.

## Validation before freeze

Automated validator must prove:

- exactly 80 TEST + 12 DEV IDs, unique;
- exact category counts;
- every answerable expected source chunk exists in the frozen MESA_Data chunk plan;
- every evidence span is an exact substring of its referenced chunk/canonical source;
- TEST expected evidence belongs to TEST partition;
- no expected source chunk has been invented;
- relational questions have >=2 evidence groups;
- no-answer entries have no expected source chunks;
- query text is non-empty and has no accidental expected-answer annotation.

## Freeze

Write:

```text
ground_truth_test.jsonl
ground_truth_dev.jsonl
ground_truth_validation.json
ground_truth_test.sha256
ground_truth_dev.sha256
```

After TEST hash freeze, files become read-only in workflow semantics. Any edit creates a new GT version and invalidates/restarts the certification run. Never “correct” a qrel after looking at a failed query in the same run.


<!-- V3.1_IDENTITY_NAMESPACE -->
## Chunk identity namespace contract

Ground truth is authored in the **MESA_Data source namespace**. The canonical qrel field is `expected_source_chunk_ids`; do not assume a MESA public provenance `chunk_id` is byte-for-byte the same identifier.

After native full delivery is reconciled, but **before the first TEST retrieval request**, produce a frozen identity mapping derived only from deterministic publisher/ingestion/commit metadata — never from search results:

```json
{
  "source_chunk_id": "mesa-data-source-chunk-id",
  "mesa_chunk_ids": ["mesa-public-provenance-chunk-id"],
  "mesa_document_id": "...",
  "mesa_revision_id": "...",
  "source_ref": "...",
  "release_id": "...",
  "derivation": "native publisher/commit metadata",
  "run_id": "..."
}
```

Requirements:

- every answerable GT source chunk must resolve through the mapping;
- one source chunk may map to one or more MESA-visible provenance chunk IDs only when the live product contract proves that transformation;
- ambiguous, missing, many-to-many, or search-derived mappings are hard errors requiring investigation;
- write `identity_map.jsonl`, validate it deterministically, and hash it;
- freeze the map before TEST; any mapping change after TEST begins invalidates the run;
- the scorer normalizes MESA returned provenance through this map back to source IDs before qrel comparison.

The mapping artifact is not allowed to alter GT semantics; it only reconciles identifier namespaces.
