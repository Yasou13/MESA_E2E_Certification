> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 20 — RESOURCE AND PROVIDER BUDGETS

Autonomy must be bounded. An agent may not burn unlimited NVIDIA calls or loop forever on the same defect.

## Retry limits

Unless the product already implements a stricter safe policy:

```text
same external request: max 3 attempts total
same root-cause repair cycle: max 2 code-fix cycles before STOP/FAIL for human review
same phase restarted for identical external failure: max 2 times
```

Do not stack product retries + harness retries into an accidental retry storm. Record effective maximum.

## Provider call budget

Before TEST, estimate intended calls from corpus size/chunks + queries. Establish a phase budget based on expected work, not a fixed dollar price (prices can change).

At minimum track:

```text
embedding requests
embedding input count if batched
LLM extraction requests
LLM answer requests
retry requests
timeouts/rate limits
reported prompt/completion tokens where provider exposes them
wall-clock provider time
```

If actual calls exceed 2× the frozen expected phase budget without an explained bounded reason, STOP and investigate before continuing.

Never log API keys/request Authorization headers.

## Runtime resources

Sample during full native ingest and retrieval:

```text
host available RAM
MESA container RSS/memory
peak RSS if available
swap use
load/CPU summary
disk used by run/volume
container restart count
OOMKilled / kernel OOM indicators
```

Profile B is not the 24-hour soak, so there is no hard memory-leak slope gate. However:

- any OOM/Killed caused by the standard >=8 GiB Profile B environment is a hard runtime failure;
- uncontrolled disk growth or repeated crash/restart is a hard failure;
- resource observations go into final limitations even when thresholds pass.

## Timeout selection

Timeouts may be validated on provider preflight/DEV. Once TEST config freezes, timeout changes invalidate the run. A timeout must be high enough for the chosen reasoning model but finite; never use infinite waits.

