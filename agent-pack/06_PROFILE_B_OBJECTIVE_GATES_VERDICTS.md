> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 06 — PROFILE B OBJECTIVE, HARD GATES AND VERDICTS

## Primary objective

Certify real legal-data E2E behavior, not raw model intelligence. Retrieval is scored separately from answer generation so an LLM cannot hide a retrieval failure by guessing.

## Hard gates

All hard gates must pass on one final coherent run.

| Gate | Requirement |
|---|---|
| B0 | Clean exact code baselines, dedicated branches, dependencies reproducible, final GitHub Actions green |
| B1 | VM resource minimum and clean isolated run storage |
| B2 | Real NVIDIA provider contract: Nemotron passage/query 2048 + GPT-OSS completion/structured/real extraction |
| B3 | Production Docker config parity: actual container uses frozen provider/extraction identity/settings |
| B4 | MESA_Data raw integrity, encoding, canonicalization, parsing coverage, quality and release verification |
| B5 | Hash-bound H1 human approval of corpus/release and permission for full delivery |
| B6 | Native MESA_Data→MESA live contract canary passes; no bridge substitution |
| B7 | Full native delivery reaches terminal COMMITTED/valid deduplicated state for all intended chunks; exact mapping proven |
| B8 | Restart persistence and idempotent republish/retry behavior proven |
| B9 | Isolation/ACL negative tests: search, context and catalog/document/revision/chunk visibility do not cross tenant/principal scope |
| B10 | Frozen TEST retrieval metrics meet thresholds |
| B11 | Real Kùzu graph origin/provenance proven and causal ON/OFF contribution demonstrated on REL set |
| B12 | Final context-only answer grounding and abstention thresholds met |
| B13 | No OOM/Killed/catastrophic resource failure; resource/provider usage recorded |
| B14 | Evidence integrity and hash verification passes; no run/config/GT mutation after freeze |

## Benchmark composition

Target approved corpus: **60 documents**. Hard minimum: **50** eligible documents after quality/review. Do not fabricate or lower data-quality gates to reach the minimum.

Frozen scored TEST set: exactly 80 queries:

```text
40 SINGLE_DIRECT
20 SINGLE_PARAPHRASE
10 RELATIONAL / graph-relevant
10 NO_ANSWER
```

A separate 12-query DEV set is used only before TEST freeze/tuning, with disjoint evidence chunks/documents where practical.

## Retrieval thresholds

Hard metrics calculated from MESA provenance at `top_k=5`:

```text
All answerable TEST queries Recall@5        >= 0.80
Single-hop (DIRECT+PARAPHRASE) Recall@5     >= 0.90
All answerable TEST queries MRR             >= 0.70
REL complete-evidence@5                     >= 0.70
Tenant leakage                              = 0
```

`REL complete-evidence@5` means all required evidence groups for a relational qrel are represented in top 5 provenance, not merely one convenient hit.

## Answer thresholds

```text
Grounded answer pass rate on answerable TEST >= 0.80
NO_ANSWER correct abstention                 >= 0.80
Unsupported material claim rate              = 0 for answers counted as grounded PASS
Fabricated evidence chunk IDs                 = 0
```

An answer with the right legal conclusion but missing retrieved support fails groundedness.

## Graph hard evidence

At minimum:

- graph capability operational;
- public search result provenance records `graph` origin on graph-relevant queries;
- graph path/hop/assertion evidence is internally valid;
- at least 3 of 10 REL queries show a graph-origin top-5 contribution **or** the final report documents why the designed graph-relevant qrels could not engage graph and fails B11;
- graph ON vs controlled graph-OFF shadow ablation changes rank/evidence coverage for at least one REL query, proving causality rather than logging only.

Do not tune the REL questions after observing graph results.

## Allowed final verdicts

### `PROFILE_B_PASS_NATIVE`
Every hard gate passed using native MESA_Data→MESA delivery on one final run.

### `PROFILE_B_FAIL`
The run completed enough to evaluate and at least one hard product/quality/metric gate failed.

### `PROFILE_B_BLOCKED_EXTERNAL`
Certification cannot validly continue due to external infrastructure outside the repositories, e.g. persistent NVIDIA outage, official-source outage, GitHub CI unavailable, or environment limitation that the agent is not authorized to change. Include exact evidence and do not score missing calls as failures.

### `PROFILE_B_DIAGNOSTIC_BRIDGE_ONLY`
A non-native bridge/harness path can demonstrate downstream MESA behavior, but the native MESA_Data publisher gate did not pass. **This is not a Profile B pass.**

### `PROFILE_B_ABORTED_HUMAN_GATE`
H1 approval was rejected or not provided. No full corpus delivery occurs.

## Forbidden verdict inflation

Never say “MVP ready” from Profile B alone. Overall MVP certification requires the other designated profiles and final combined decision.

