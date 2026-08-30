> **Profile B Autonomous Agent Pack v3.0**  
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
3. record expected chunk ID(s)/evidence groups
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
  "expected_chunk_ids": ["..."],
  "evidence_groups": [["chunk-a"], ["chunk-b", "chunk-c"]],
  "evidence_spans": [{"chunk_id":"...","text":"exact substring"}],
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
expected_chunk_ids=[]
required_facts=[]
expected_answer="YETERSİZ KANIT"
```

A NO_ANSWER question must be plausible but not answerable from the selected frozen corpus. Verify this only from source/canonical indexes, not from MESA search.

## Validation before freeze

Automated validator must prove:

- exactly 80 TEST + 12 DEV IDs, unique;
- exact category counts;
- every answerable expected chunk exists in the frozen MESA_Data chunk plan;
- every evidence span is an exact substring of its referenced chunk/canonical source;
- TEST expected evidence belongs to TEST partition;
- no expected chunk has been invented;
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

