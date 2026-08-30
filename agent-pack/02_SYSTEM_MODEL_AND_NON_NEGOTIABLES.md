> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 02 — SYSTEM MODEL AND NON-NEGOTIABLES

## Product boundary

Profile B evaluates the integrated chain:

```text
Official Turkish legal source
  → MESA_Data raw immutable artifact
  → decode / parse / canonicalize
  → quality + review
  → immutable verified release
  → deterministic SourceChunk plan
  → native MESA_Data publisher
  → MESA V4 authenticated/session-scoped ingestion
  → async mutation COMMITTED
  → canonical SQL + LanceDB + FTS/assertions + Kùzu projection
  → public MESA V4 search
  → retrieval provenance
  → context-only GPT-OSS answer
  → deterministic scoring
```

A pass must prove the chain. Testing components independently is useful for diagnosis but cannot substitute for the chain.

## What Profile B is for

Profile B answers: “Can the current product ingest and retrieve a meaningful, approved real legal corpus with the intended external models and preserve enough provenance/isolation to support grounded answers?”

It does **not** attempt to certify long-duration memory-leak behavior (Profile A) or exhaustive temporal/contradiction/crash/adversarial semantics (Profile C), although B includes bounded restart, idempotency and graph checks because they are necessary to trust the benchmark.

## Invariants

The following are non-negotiable:

- **Native publisher:** Full PASS requires MESA_Data's product publisher to interoperate with MESA. Diagnostic harness bridges do not satisfy this.
- **Real providers:** Do not replace NVIDIA models with mocks/local substitutes for hard provider gates.
- **Asymmetric embedding:** documents use Nemotron `input_type=passage`; queries use `input_type=query`.
- **Embedding identity:** expected model `nvidia/nemotron-3-embed-1b`, dimension 2048, configured version `nemotron-qpass-v1` unless the current product contract deliberately changes and is requalified.
- **Extraction:** expected model `openai/gpt-oss-20b`, Turkish extraction, real `FactExtractionService`/current production equivalent, with sufficient bounded output budget (archive baseline: 4096).
- **Immutable evidence:** failed runs remain available.
- **One coherent final run:** do not cherry-pick passing phases from different code SHAs/runs.
- **No TEST tuning:** TEST is evaluation, not development.
- **No source falsification:** never edit official legal text, canonical expected evidence, or qrels merely to fit MESA output.
- **No secret exposure:** redact credentials and bearer headers.
- **Authorization:** tenant/dataset/session boundaries are hard gates, not diagnostics.
- **Graph proof:** code presence or Kùzu writes alone do not prove graph retrieval usefulness.
- **Grounding:** final answer correctness without evidence is a fail for grounded-answer scoring.

## Evidence hierarchy

Strongest to weakest:

1. current-run live HTTP/runtime evidence with exact code/config hashes;
2. deterministic state inspection and immutable artifacts;
3. integration tests against real local services;
4. unit/regression tests;
5. static source inspection;
6. documentation/README assertions.

Higher evidence should be used where a hard gate permits it.

## Truth over automation

The agent may stop with a failure. It must not “help” by silently substituting:

- a different model;
- a different endpoint;
- a fabricated official source;
- a smaller/easier query set after results are seen;
- relaxed thresholds;
- a mock server;
- a manual direct MESA client bridge in place of the native publisher;
- a hidden second attempt whose first failure is deleted.

