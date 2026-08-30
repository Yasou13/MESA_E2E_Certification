> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 19 — FAILURE TRIAGE, REPAIR AND RESTART

## Failure classes

Every failure gets exactly one primary class:

```text
PRODUCT_MESA
PRODUCT_MESA_DATA
CROSS_REPO_CONTRACT
DEPLOYMENT_CONFIG
CERT_HARNESS
DATA_QUALITY
EXTERNAL_NVIDIA
EXTERNAL_OFFICIAL_SOURCE
ENVIRONMENT
HUMAN_GATE
EXPECTED_BENCHMARK_MISS
```

## First response

On failure:

1. stop issuing repeated broad commands;
2. preserve stdout/stderr/request status/log slice and current SHAs;
3. determine whether state was mutated;
4. create a minimal reproducer;
5. compare live code contract rather than guessing;
6. classify transient vs deterministic.

## Repairable product bug workflow

```text
failure evidence
→ minimal reproducer
→ root cause
→ focused regression
→ minimal fix
→ focused test
→ relevant repository local CI-equivalent
→ inspect diff
→ atomic green commit
→ optionally push cert branch
→ mark current run INVALIDATED_CODE_CHANGE
→ new RUN_ID + clean run state
→ Phase 0
```

Do not continue the old benchmark “from where it failed.”

## What the agent may fix

Allowed:

- API/payload contract mismatch;
- missing Compose env wiring;
- provider error classification;
- deterministic parser/encoding/data-loss bug;
- idempotency/ledger bug;
- provenance mapping bug;
- authorization defect;
- benchmark harness/scorer bug;
- other minimal blockers actually reproduced by Profile B.

Not allowed to force PASS:

- lower metric thresholds;
- delete difficult questions/documents after results;
- rewrite expected answers/qrels from MESA outputs;
- disable graph/isolation/security gates;
- switch models/providers;
- ignore 5xx/timeouts as empty results;
- skip H1;
- use a bridge and relabel it native.

## Raw-source snapshot policy across restarted runs

A full restart means re-running Phase 0 and every relevant pipeline/gate under a new RUN_ID; it does not require intentionally changing the legal bytes under test. To preserve comparability, an immutable hash-addressed raw-source snapshot may be reused as input to a clean MESA_Data root **only when** its original official URL/acquisition metadata/SHA are preserved and the repair does not question whether those bytes were acquired correctly. The new run must re-verify every raw SHA and rerun decode/canonical/quality/release logic from those bytes.

If the defect touches collection/download/redirect/MIME/TLS/source-selection semantics, repeat the affected live official-source acquisition checks. Preserve both the original and newly acquired raw manifests; never silently replace source bytes under an existing GT/release hash.

This policy gives “start from scratch” clean state while preventing external website drift from becoming an unrecorded benchmark change.

## Transient provider/external failure

Use bounded retries from `20_RESOURCE_AND_PROVIDER_BUDGETS.md`. If exhausted, preserve state and end/pause as `PROFILE_B_BLOCKED_EXTERNAL`. Do not make speculative product changes solely because NVIDIA was slow once.

## Data-quality failure

A selected document failing quality is not automatically a product bug. Exclude according to predeclared selection/quality policy and replace from the deterministic candidate list **before corpus/GT freeze**. After freeze, membership changes invalidate the run.

If the quality system itself demonstrably corrupts or fails to detect material source loss, fix the product and restart.

## Repair journal

Each failure record includes:

```text
failure_id
run_id
phase
UTC
classification
symptom
minimal reproduction
root cause
evidence paths
pre-fix SHAs
changed files/tests
commit SHA(s)
post-fix verification
old run invalidation reason
next RUN_ID
```


## Post-freeze change rule

After the official contract freeze, any material product/config/harness/scorer
fix makes the current run `INVALIDATED_CODE_CHANGE`.

Preserve evidence, make the minimal fix, test/commit it, create a new RUN_ID
and restart from bootstrap/Phase -1/Phase 0.

Do not continue the official TEST from the failure point.
