> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 22 — LIVE STATUS TEMPLATE

Create/copy this as `<RUN_ROOT>/status.md` and update it without deleting prior failure references.

```markdown
# Profile B Live Status

RUN_ID: ...
State: RUNNING | WAITING_H1 | INVALIDATED_CODE_CHANGE | BLOCKED_EXTERNAL | COMPLETE
Started UTC: ...
Last update UTC: ...

## Code
MESA branch/SHA: ...
MESA_Data branch/SHA: ...
Git dirty: no/no

## Frozen identities
Corpus manifest SHA: pending
Release manifest SHA: pending
GT TEST SHA: pending
Benchmark config SHA: pending
H1 approval: pending

## Phases
- P0 Baseline: PENDING
- P1 Provider/runtime: PENDING
- P2 MESA_Data: PENDING
- P3 H1: PENDING
- P4 GT/config freeze: PENDING
- P5 Native canary: PENDING
- P6 Full publish: PENDING
- P7 Restart/idempotency/isolation: PENDING
- P8 Retrieval TEST: PENDING
- P9 Graph proof: PENDING
- P10 Answers: PENDING
- P11 CI/integrity: PENDING
- P12 Verdict: PENDING

## Current gate
...

## Provider usage
Embedding calls: ...
Extraction calls: ...
Answer calls: ...
Retries/timeouts: ...

## Failures
- none

## Repairs/commits
- none

## Next action
...
```

Statuses are factual. Never mark a phase PASS merely because work started.

