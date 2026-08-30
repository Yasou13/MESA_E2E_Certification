> **Profile B Autonomous Agent Pack v3.1**
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

- [ ] read all v3.1 files, including `28_AUTONOMOUS_DECISION_DOCTRINE.md`
- [ ] `SHA256SUMS.txt` verifies
- [ ] no v1 master prompt accidentally used
- [ ] result root writable
- [ ] first RUN_ID created only after final cert-branch SHAs are known

If any hard item fails, do not start the scored benchmark.


<!-- V3.1_PRELAUNCH_ADDITIONS -->
## v3.1 additional prelaunch checks

- [ ] certification repository clean, exact `main` fetched, cert branch clean
- [ ] exact `origin/main` SHAs for all three repositories recorded before RUN_ID creation
- [ ] no active-run repository will auto-pull/merge upstream changes
- [ ] deterministic acquisition expansion policy configured/recorded
- [ ] GT uses `expected_source_chunk_ids`, not an assumed MESA ID namespace
- [ ] identity-mapping algorithm/contract frozen before TEST
- [ ] decision journal path writable and schema known
- [ ] `reports/releases/` tracked final-promotion location available
- [ ] ambiguous answer policy cannot create a second human gate

## Workspace hygiene gate

Before Phase 0 verify:

- [ ] Phase -1 completed.
- [ ] Fresh RUN_ID exists.
- [ ] `workspace-baseline.json` exists.
- [ ] MESA mutable storage is clean for this RUN_ID.
- [ ] MESA_Data mutable data root is clean for this RUN_ID.
- [ ] Old runtime state is not reused.
- [ ] Docker state was inventoried.
- [ ] Current-run Docker state is isolated.
- [ ] No unknown user data was deleted.
- [ ] No secret value was printed.
- [ ] Three repositories were safely updated from `origin/main`.
- [ ] Exact repository SHAs were recorded/frozen.

## VM bootstrap gate

Before Phase -1/Phase 0 verify:

- [ ] `30_VM_BOOTSTRAP_AND_CANONICAL_WORKSPACE_LAYOUT.md` executed.
- [ ] Canonical root resolved.
- [ ] Canonical MESA checkout resolved.
- [ ] Canonical MESA_Data checkout resolved.
- [ ] Canonical certification checkout resolved.
- [ ] All three Git origins verified.
- [ ] Old non-canonical checkouts preserved unless proven safe to relocate.
- [ ] No arbitrary Desktop/Downloads checkout is being used as accidental runtime authority.
- [ ] RUN_ID-scoped runtime can be created.
- [ ] Mutable databases are outside Git repositories.
- [ ] Docker namespace isolation is available or equivalent isolation is proven.
- [ ] `bootstrap-layout.json` will be/has been written.

## Benchmark integrity preflight

Before official TEST:

- [ ] No ground-truth/qrel data can flow into product requests.
- [ ] Certification repo SHA is frozen.
- [ ] Harness/scorer hashes are frozen.
- [ ] Query/GT/identity-map hashes are frozen.
- [ ] `contract-freeze.json` exists.
- [ ] `determinism-manifest.json` exists.
- [ ] Scorer canaries PASS.
- [ ] `health-pre-test.json` is healthy.
- [ ] No TEST result has been used for tuning.
