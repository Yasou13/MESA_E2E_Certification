# 31 — Benchmark Integrity, Freeze, Determinism and Finalization

## Purpose

This document closes the final false-PASS and reproducibility risks in
MESA Profile B.

It defines:

- benchmark information barriers,
- certification contract freeze,
- harness/scorer freeze,
- determinism/environment manifest,
- pre/post health snapshots,
- scorer canaries,
- dependency/supply-chain constraints,
- methodology-change authority,
- post-run finalization and teardown.

This document is mandatory.

---

# 1. Benchmark information barrier

Ground truth is an **oracle for scoring only**.

The following MUST NOT be exposed to MESA retrieval, MESA ingestion,
fact extraction, GPT-OSS final-answer generation, query rewriting, graph
retrieval, embedding requests, or any product runtime component:

- expected answers,
- `required_facts`,
- `forbidden_claims`,
- expected evidence IDs,
- expected source chunk IDs,
- expected MESA chunk IDs,
- qrel groups,
- scorer labels,
- pass/fail labels,
- acceptable answer patterns,
- test-specific expected graph paths,
- any hidden evaluator annotation.

The test query text itself may of course be sent to MESA.

The oracle may be read only **after the raw product response for that query has
been persisted**.

---

# 2. Query execution/scoring separation

For every TEST query, the required order is:

```text
frozen TEST query
        ↓
construct product request from allowed query/runtime config only
        ↓
send request to MESA
        ↓
persist complete raw response
        ↓
persist request metadata that contains no oracle data
        ↓
only then load ground-truth/qrel
        ↓
score deterministically
```

A harness implementation that loads qrels before request construction is not
automatically invalid, but it MUST prove that oracle-derived values cannot flow
into the product request.

Preferred design: separate execution and scoring processes/files.

---

# 3. Prohibited oracle leakage

Hard FAIL / invalid run if any TEST request to the product contains oracle
information that would not exist in real use.

Examples:

```text
expected_chunk_id in request metadata
required_facts in final-answer prompt
expected answer in extraction prompt
gold evidence IDs in retrieval filters
gold document ID used to narrow retrieval
REL expected path passed to graph search
```

Debugging code that has access to both request and qrel objects must be treated
as high risk.

---

# 4. DEV and TEST separation

DEV may be used for:

- implementation debugging,
- scorer development,
- threshold-independent correctness checks,
- prompt/config tuning allowed by the certification plan.

TEST may NOT be used for:

- choosing top_k,
- changing RRF,
- changing graph hops,
- changing prompts,
- changing model,
- changing corpus,
- changing qrels,
- changing thresholds,
- selecting favorable queries,
- changing scorer semantics,
- choosing evidence normalization rules after seeing results.

If TEST results influence any of these, invalidate the run.

---

# 5. Certification contract freeze

Before the first official TEST query, freeze and hash:

- MESA Git SHA,
- MESA_Data Git SHA,
- MESA_E2E_Certification Git SHA,
- `agent-pack/SHA256SUMS.txt`,
- all harness source files,
- all scorer source files,
- all config files,
- TEST query file,
- DEV query file,
- ground-truth/qrel files,
- identity mapping,
- corpus/release manifest,
- prompts,
- retrieval settings,
- graph settings,
- model identities,
- thresholds,
- test class counts,
- verdict rules.

Write:

```text
runs/<RUN_ID>/contract-freeze.json
runs/<RUN_ID>/contract-freeze.SHA256
```

The freeze must be created before official TEST execution.

---

# 6. Code/config mutation after freeze

After `contract-freeze.json` is created, any material change to:

- MESA,
- MESA_Data,
- certification repo,
- harness,
- scorer,
- query set,
- ground truth,
- identity mapping,
- prompts,
- retrieval config,
- graph config,
- provider/model config,
- threshold/verdict logic,

invalidates the current official run.

Required status:

```text
INVALIDATED_CODE_CHANGE
```

Then:

1. preserve old evidence,
2. make the minimal justified fix,
3. test it,
4. commit it,
5. create a new RUN_ID,
6. repeat bootstrap/Phase -1/Phase 0,
7. refreeze,
8. rerun TEST from the beginning.

No partial continuation.

---

# 7. Methodology-change authority

The agent may autonomously fix:

- product bugs,
- integration bugs,
- deployment/config bugs,
- harness implementation bugs,
- scorer implementation bugs,

when the intended certification semantics remain unchanged.

The agent MUST NOT autonomously change the meaning of the certification.

Examples requiring run invalidation and human approval before adoption:

- lowering a hard gate,
- changing the definition of a retrieval hit,
- changing the denominator,
- removing difficult TEST queries,
- reclassifying failures as exclusions,
- changing what constitutes groundedness,
- weakening tenant isolation,
- replacing native publish with a bridge,
- changing the required graph proof,
- changing PASS_NATIVE semantics,
- changing TEST composition because results are poor.

Record the proposed methodology change in `decision_log.jsonl`.

The current run must not receive PASS based on a methodology change made after
results were observed.

---

# 8. Determinism/environment manifest

Before official TEST execution, write:

```text
runs/<RUN_ID>/determinism-manifest.json
```

Record at least:

- UTC timestamp,
- timezone,
- locale,
- kernel/OS,
- architecture,
- CPU count,
- total RAM,
- Python version,
- uv version,
- git version,
- Docker version,
- Docker Compose version,
- NVIDIA/OpenAI-compatible SDK version,
- MESA SHA,
- MESA_Data SHA,
- certification SHA,
- embedding provider/model/version/dimension,
- LLM provider/model,
- extraction model,
- temperature values,
- top_p values if used,
- provider seed if supported,
- `seed_supported` boolean,
- local random seeds,
- corpus ordering algorithm,
- query ordering algorithm,
- sampling algorithm,
- retry policy,
- concurrency settings,
- timeout settings.

If the provider does not support deterministic seeds, record:

```json
{
  "seed_supported": false
}
```

Do not fabricate determinism.

---

# 9. Stable ordering and randomness

Any sampling, corpus selection, query ordering or test fixture selection MUST
be deterministic once frozen.

Use:

- explicit sorting,
- explicit seed,
- explicit selection algorithm.

Do not rely on:

- filesystem iteration order,
- hash-map order,
- unordered database output,
- current clock randomness,
- provider response order unless contractually stable.

Record the seed and algorithm.

---

# 10. Pre-test health snapshot

Immediately before the first official TEST query, capture:

```text
runs/<RUN_ID>/health-pre-test.json
```

Include, where available:

- MESA API health,
- worker health,
- mutation backlog,
- failed/dead-letter mutation count,
- SQLite availability,
- LanceDB availability,
- Kùzu availability,
- container status,
- container restart count,
- disk usage,
- free disk,
- system RAM,
- process/container memory,
- OOM indicators,
- current model/provider identity,
- current config/freeze hash.

If the system is already unhealthy, do not start official TEST.

---

# 11. Post-test health snapshot

Immediately after the official TEST phase, before final PASS computation,
capture:

```text
runs/<RUN_ID>/health-post-test.json
```

Check:

- API still healthy,
- workers still alive,
- no unexpected container restarts,
- no OOM kill,
- no unexplained mutation backlog,
- storage backends still readable,
- no fatal provider/runtime errors hidden by harness retries,
- disk not exhausted.

A benchmark that numerically passes while the system silently crashed or lost a
required component is not PASS_NATIVE.

---

# 12. Infrastructure errors are not retrieval misses

HTTP 5xx, timeout, provider outage, process crash, OOM, unavailable storage or
other infrastructure failures must not be silently counted as ordinary
retrieval misses.

Classify them separately.

The benchmark report must show:

- valid scored queries,
- infrastructure failures,
- external provider failures,
- excluded queries and exact reason, if exclusions are allowed,
- denominator actually used.

Exclusions must follow pre-frozen rules.

---

# 13. Scorer canaries

Before scoring official TEST results, the scorer MUST pass synthetic canaries
that are not part of the product benchmark score.

At minimum:

1. obvious hit at rank 1,
2. obvious hit at rank 5,
3. no-hit case,
4. REL query with all evidence groups,
5. REL query missing one evidence group,
6. equivalent/normalized provenance identity case,
7. source-chunk ID != MESA public chunk ID mapping case,
8. malformed provenance case,
9. infrastructure-error case,
10. intentionally wrong provenance case that MUST score as MISS.

Write:

```text
runs/<RUN_ID>/scorer-canary-results.json
```

All required canaries must PASS before official scoring.

Canary results never count toward product metrics.

---

# 14. Final-answer evaluation information barrier

The final-answer model may receive only the allowed retrieved context and
normal answer-generation instructions.

It MUST NOT receive:

- ground truth,
- required facts,
- expected answer,
- forbidden claims,
- scorer rubric,
- gold evidence IDs,
- PASS/FAIL labels.

Required order:

```text
raw retrieval response persisted
        ↓
allowed top-k context constructed
        ↓
final-answer request sent
        ↓
raw final-answer response persisted
        ↓
only then evaluator loads ground truth
        ↓
deterministic grading
```

---

# 15. Supply-chain and dependency rule

The agent MUST prefer the project's existing:

- lockfiles,
- extras,
- package metadata,
- documented toolchain.

Do not solve a certification problem by casually installing arbitrary latest
packages globally.

Forbidden as a default strategy:

```text
pip install <random-package>
pip install --upgrade everything
curl | sudo bash
unbounded global npm/pip installs
```

If a new dependency is genuinely required for the certification harness:

1. prove existing dependencies cannot reasonably do the job,
2. choose the smallest maintained dependency,
3. pin/lock it,
4. add it to the correct repo,
5. run tests,
6. commit the dependency change,
7. invalidate any frozen run,
8. record name/version/reason in evidence.

Product dependencies belong in the product repo if they are truly product
requirements; certification-only dependencies belong in the certification
repo.

---

# 16. External provider/version observability

For NVIDIA/provider calls record where available:

- endpoint,
- model name,
- model revision/version/header,
- SDK version,
- request timestamp,
- retry count,
- latency,
- token usage,
- finish reason,
- provider request ID.

Do not record secrets.

If the remote provider exposes only a model name and no immutable backend
revision, state this limitation in the final report.

---

# 17. Finalization order

After all gates are computed, finalization order is:

```text
complete scoring
        ↓
capture post-test health
        ↓
run final agent self-audit
        ↓
write final-report.md
        ↓
write run_manifest.json
        ↓
write evidence-index.json
        ↓
promote compact audit bundle
        ↓
compute SHA256SUMS.txt
        ↓
verify SHA256SUMS.txt
        ↓
mark run final
        ↓
safe teardown
```

Do not modify hashed artifacts after checksums are generated.

If an artifact must change, regenerate the affected manifest/checksums and
record the reason before declaring the run final.

---

# 18. Safe teardown

After final evidence is sealed:

- stop current certification-owned services safely,
- preserve final RUN_ID mutable state until evidence integrity is confirmed,
- preserve failed/invalidated runs,
- do not delete current evidence,
- do not prune unrelated Docker resources,
- do not delete secrets,
- do not reuse the finalized RUN_ID for another run.

A later cleanup may remove clearly disposable certification-owned runtime only
after evidence has been promoted and verified.

---

# 19. Final evidence promotion

The compact final bundle under:

```text
reports/releases/<RUN_ID>/
```

should include or reference, at minimum:

```text
final-report.md
run_manifest.json
gate-results.json
retrieval-summary.json
answer-summary.json
graph-summary.json
resource-provider-summary.json
frozen-identities.json
identity-map-summary.json
decision-summary.json
repair-summary.json
evidence-index.json
contract-freeze.json
determinism-manifest.json
health-pre-test.json
health-post-test.json
scorer-canary-results.json
SHA256SUMS.txt
```

Large raw evidence may remain outside Git, but the compact bundle must make the
verdict auditable.

---

# 20. False-PASS checks

Before `PROFILE_B_PASS_NATIVE`, answer all of these:

- Could the product have seen expected answers or qrels?
- Could the final-answer model have seen `required_facts`?
- Could a gold document/chunk ID have narrowed retrieval?
- Did the scorer change after TEST results were observed?
- Did thresholds/verdict semantics change?
- Did TEST results influence config tuning?
- Does the certification SHA match the frozen SHA?
- Do harness/scorer hashes match the frozen hashes?
- Did all scorer canaries PASS?
- Was the system healthy before and after TEST?
- Were infrastructure failures separated from retrieval misses?
- Are random seeds/orderings recorded?
- Was a new dependency added after freeze?
- Was final evidence sealed before teardown?

Any unresolved "yes/maybe" that can produce a false PASS prevents
`PROFILE_B_PASS_NATIVE`.

---

# 21. Required evidence

This document adds these required artifacts:

```text
runs/<RUN_ID>/contract-freeze.json
runs/<RUN_ID>/contract-freeze.SHA256
runs/<RUN_ID>/determinism-manifest.json
runs/<RUN_ID>/health-pre-test.json
runs/<RUN_ID>/health-post-test.json
runs/<RUN_ID>/scorer-canary-results.json
```

Material integrity/methodology decisions must also appear in:

```text
runs/<RUN_ID>/decision_log.jsonl
```

---

# 22. PASS conditions

Benchmark-integrity PASS requires:

- no oracle leakage,
- execution/scoring separation proven,
- DEV/TEST separation respected,
- certification contract frozen before TEST,
- no post-freeze material mutation,
- determinism manifest recorded,
- scorer canaries all pass,
- pre-test system healthy,
- post-test system healthy,
- infra failures correctly classified,
- supply-chain policy respected,
- methodology not autonomously weakened,
- final artifacts sealed and checksum-verified,
- teardown performed only after evidence finalization.

Failure of any integrity condition invalidates or blocks the run rather than
being hidden inside product metrics.

## Canonical MESA runtime semantics

The official RUN must freeze the semantic runtime contract from
`32_PROFILE_B_CANONICAL_MESA_RUNTIME_LOCK.md`.

Mode/model/provider settings are not tunable from TEST results.

Operational parameters such as timeout/concurrency may be discovered before
freeze, but become immutable for the official RUN once frozen.

## Executable harness and semantic GT lock

Document 33 is mandatory before official TEST.

Freeze:

- executable harness/scorer source hashes,
- scoring-normalization version/hash,
- GT semantic-validation result,
- NO_ANSWER negative-evidence audit,
- identity-map validation result,
- oracle-leakage audit,
- harness self-test/readiness artifacts.

A changed harness/scorer/normalizer after freeze invalidates the RUN.

## Resource guard freeze

Before official TEST freeze:

- resource-pressure thresholds,
- monitor cadence,
- harness concurrency,
- harness batch size,
- OOM/cgroup baseline,

and hash/reference `resource-guard-config.json`.

A material resource-policy change after TEST begins invalidates the RUN if it
can affect execution/results.

Hidden OOM/restart invalidates PASS regardless of numerical benchmark metrics.

## Efficiency state and benchmark integrity

Operational caches/checkpoints from document 35 may be updated as execution
progresses, but they must never become scoring oracles.

Before official TEST, freeze all execution parameters that can affect results,
including relevant concurrency/batch/retry/provider settings.

Reusing unchanged provider/discovery evidence is allowed only when its
dependency hashes/identities match.

Re-running an official TEST query to improve its result is forbidden.
