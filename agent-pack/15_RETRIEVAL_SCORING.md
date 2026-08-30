> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 15 — RETRIEVAL SCORING

## Source of truth for a hit

A retrieval hit is based on **MESA returned provenance**, not entity text similarity or the LLM's answer.

For each search result, collect all provenance chunk IDs/document/revision IDs exposed by the current public V4 response. A result is relevant when its provenance intersects the qrel's expected evidence according to the rules below.

## Single-hop scoring

For `SINGLE_DIRECT` and `SINGLE_PARAPHRASE`:

- relevant result = any result whose provenance contains an expected chunk ID;
- rank = first relevant result rank;
- Recall@1 = 1 if rank 1 else 0;
- Recall@5 = 1 if rank <=5 else 0;
- Reciprocal Rank = `1/rank`, else 0.

If multiple chunk IDs are equivalent evidence alternatives inside one evidence group, any one counts.

## Relational scoring

REL qrels contain >=2 evidence groups. For each top-5 response calculate:

```text
group_coverage@5 = represented evidence groups / required evidence groups
complete_evidence@5 = 1 only if every required group is represented
```

Also calculate ordinary first-relevant MRR for comparability, but the hard REL gate uses complete evidence.

## Overall answerable retrieval

NO_ANSWER is excluded from answerable Recall/MRR denominators. Report it separately; retrieval may return semantically similar material even when evidence is insufficient, so abstention is primarily graded in the answer stage.

Report:

```text
Recall@1
Recall@5
MRR
by category
by document/source type
REL average group coverage@5
REL complete-evidence@5
```

## Failure handling

If a query fails because of provider timeout, service crash, 5xx backend unavailability, corrupt run state or other infrastructure issue, mark the run **invalid**. Do not record that query as rank=∞/wrong and continue to a deceptively lower metric.

A valid 200 response with no relevant result is a genuine retrieval miss.

## Raw evidence

For every query save before scoring:

```json
{
  "run_id":"...",
  "query_id":"Q001",
  "request": {"query":"...","limit":5,"dataset_ids":["..."]},
  "response_status":200,
  "results":[...full bounded public response...],
  "latency_ms":123,
  "utc":"..."
}
```

Redact secrets, not provenance.

## Scorer integrity

The scorer must be deterministic and unit-tested with synthetic fixtures covering:

- no hit;
- hit at 1/5;
- multiple provenance items;
- equivalent chunks;
- REL multiple groups;
- malformed/missing provenance;
- infrastructure-error record exclusion/invalidation.

If scorer code changes after TEST begins, invalidate and rerun from Phase 0 per policy.

