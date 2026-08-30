> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 25 — POST-FIX / PRELAUNCH CHECKLIST

Run this after the user's pending MESA and MESA_Data fixes are merged to `main`, and again after any certification-branch repair before starting a fresh Profile B run.

## Repository state

- [ ] MESA clean, exact main fetched, cert branch clean
- [ ] MESA_Data clean, exact main fetched, cert branch clean
- [ ] baseline SHAs recorded
- [ ] no unexplained local patches/stashes
- [ ] lockfiles unchanged unless intentional product fix

## Known archive issues revalidated

- [ ] MESA extraction max-token/schema/timeout fixes still present and tests pass
- [ ] Compose propagates every external embedding identity/base/key/version setting required by current code
- [ ] Compose propagates extraction model/lang/max-token settings required by current code
- [ ] production image contains OpenAI adapter dependency
- [ ] MESA_Data native publisher matches live MESA health/publish/mutation/session contract
- [ ] idempotency is supplied in the exact current MESA-consumed form
- [ ] source/version/chunk→MESA document/revision/chunk mapping is deterministic
- [ ] at least one real local cross-repo publisher integration test passes

## MESA provider

- [ ] Nemotron document=passage runtime PASS
- [ ] Nemotron query=query runtime PASS
- [ ] dimension 2048, finite/normalized
- [ ] GPT-OSS plain completion PASS
- [ ] simple structured Pydantic PASS
- [ ] real current fact-extraction service PASS
- [ ] Docker container sees same frozen config and repeats canary behavior

## MESA_Data

- [ ] cp1254/Windows-1254 regression PASS
- [ ] no lossy source decode path found
- [ ] parsing coverage guard exercised
- [ ] bulk version review tested
- [ ] raw↔canonical side-by-side tested
- [ ] release build+verify works
- [ ] deterministic SourceChunk/idempotency tests pass

## VM

- [ ] RAM >=8 GiB
- [ ] disk free >=30 GiB
- [ ] Docker healthy
- [ ] NVIDIA secret present without printing
- [ ] network/official sources/NVIDIA reachable
- [ ] GitHub credentials/CI observability available for final hard gate

## Agent pack

- [ ] read all v2 files
- [ ] `SHA256SUMS.txt` verifies
- [ ] no v1 master prompt accidentally used
- [ ] result root writable
- [ ] first RUN_ID created only after final cert-branch SHAs are known

If any hard item fails, do not start the scored benchmark.

