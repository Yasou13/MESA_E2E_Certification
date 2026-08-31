> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 27 — FINAL AGENT SELF-AUDIT

Before assigning a final verdict, run this adversarial self-review. The purpose is to catch a false PASS created by automation mistakes.

## A. Coherent-run check

- [ ] Every hard-gate PASS belongs to the same final RUN_ID, except a prior H1 authorization may be referenced only under the explicit hash-bound reuse rule below.
- [ ] MESA SHA did not change during that run.
- [ ] MESA_Data SHA did not change during that run.
- [ ] Harness/scorer/config-generation code did not change during that run.
- [ ] No evidence was copied from an invalidated run as if produced by the final run.

## B. Native-path check

- [ ] Full legal corpus used MESA_Data's native publisher engine/product path.
- [ ] No direct `MesaV4Client`/curl bridge substituted for native publisher at the hard gate.
- [ ] No mock/respx server was used for the live native gate.
- [ ] MESA HTTP/OpenAPI contract used by publisher matches the final MESA SHA.

Search the final scripts/logs for suspicious bypass markers such as direct bulk insert loops, mock URLs and local staging references; explain legitimate occurrences.

## C. Ground-truth leakage check

- [ ] GT generation process had no MESA retrieval outputs as input.
- [ ] GT generation process had no MESA extraction/graph output as input.
- [ ] TEST hash predates first TEST retrieval request.
- [ ] TEST qrels/questions were not edited after seeing misses.
- [ ] DEV and TEST expected evidence are disjoint as designed.

## D. Benchmark-tuning check

- [ ] Config freeze hash predates first TEST request.
- [ ] No top_k/RRF/graph/prompt/filter/model/timeout changes occurred during TEST.
- [ ] Any prior attempt with a different config is clearly DEV or belongs to an invalidated run.

## E. Failure-accounting check

- [ ] 5xx/timeouts/provider failures were never converted to rank misses/incorrect answers.
- [ ] Every invalid run has an invalidation record and reason.
- [ ] No failed query/result file was deleted because a retry later passed.
- [ ] Bounded retry budgets were respected.

## F. Data integrity/H1 check

- [ ] Raw SHA verification passed.
- [ ] Selected versions correspond exactly to approved H1A inputs.
- [ ] H1B exact release hash matches delivered release.
- [ ] Human decision text is literal, not agent-generated.
- [ ] No canonical/release bytes changed after H1B.

## G. Retrieval/provenance check

- [ ] Hit scoring uses expected chunk/source provenance, not answer text/entity-name similarity.
- [ ] REL complete-evidence logic requires all groups.
- [ ] A sample of scorer outputs was manually recomputed by deterministic script/assertions.
- [ ] Every reported graph-origin hit has valid path evidence.

## H. Answer-grounding check

- [ ] A correct world-knowledge guess without evidence was not counted grounded PASS.
- [ ] Evidence IDs are subsets of retrieved context IDs.
- [ ] NO_ANSWER scoring requires exact abstention semantics.
- [ ] Same GPT-OSS model was not used as the sole hard-gate judge of itself.

## I. Isolation/security check

- [ ] Negative ACL tests used genuinely distinct principals/scopes rather than one admin key.
- [ ] Zero protected Tenant B content/provenance was observed from Tenant A.
- [ ] No security feature was disabled to make publisher/testing easier.
- [ ] Evidence/logs contain no API key/bearer secret.

## J. Resource/remote reproducibility check

- [ ] No OOMKilled/repeated crash hidden from summary.
- [ ] Provider request/retry/token counters are reported.
- [ ] Remote model alias/revision limitation is disclosed if immutable revision unavailable.

## K. Git/CI check

- [ ] Worktrees clean.
- [ ] Every final product fix is committed on `cert/profile-b-e2e`.
- [ ] Final branch SHAs are pushed when required.
- [ ] GitHub Actions status corresponds to the exact reported SHAs.
- [ ] No main/force-push/merge was performed without authorization.

## L. Integrity check

- [ ] Final report does not contain its own SHA value.
- [ ] External `SHA256SUMS.txt` verifies.
- [ ] Final manifest references existing evidence paths.
- [ ] Gate table and executive verdict agree.

## Challenge question

Before PASS, answer in the internal/final audit log:

> “What is the strongest evidence that this run could still be a false positive?”

Investigate that possibility. If unresolved and material to a hard gate, do not pass.

Only after all applicable items pass may the agent mechanically apply the verdict rules.


<!-- V3.1_SELF_AUDIT_ADDITIONS -->
## M. H1 reuse exception audit

If H1 approval originated in a prior run:

- [ ] `h1_origin_run_id` is recorded;
- [ ] selected/corpus/review/release/chunk-plan hashes are bit-identical;
- [ ] canonical bytes are identical;
- [ ] no relevant MESA_Data code changed;
- [ ] original literal approval authorized the exact delivered release hash;
- [ ] the final run references the prior artifact/hash and does not misrepresent it as newly generated.

If any item fails, H1 must be reacquired.

## N. Autonomous-decision audit

- [ ] every material unspecified-case decision appears in `decision_log.jsonl`;
- [ ] chosen actions were minimal, reversible where possible, architecture-consistent, and did not weaken gates;
- [ ] no decision modified TEST/GT/corpus/thresholds after freeze to improve results;
- [ ] irreversible/security-sensitive/benchmark-definition decisions were not taken without authorization.

## O. Identity-namespace audit

- [ ] qrels use MESA_Data source chunk IDs;
- [ ] frozen identity-map SHA predates first TEST request;
- [ ] mapping came only from native publisher/ingestion/commit metadata, not retrieval;
- [ ] scorer fixtures prove differing source/MESA IDs normalize correctly;
- [ ] unmapped/conflicting IDs were treated as mapping integrity issues, not silent misses.

## P. Final evidence promotion audit

- [ ] final sanitized bundle exists under `reports/releases/<RUN_ID>/`;
- [ ] bundle contains final report, manifest, gate/metric summaries, decision/repair summaries, evidence index and checksum file;
- [ ] promoted bundle contains no secrets or bulky raw corpus/runtime state;
- [ ] promoted checksum verification passes;
- [ ] raw evidence remains referenced by hash/path and was not falsely replaced by summaries.

## Workspace hygiene self-audit

Before any final PASS ask:

- Did this run start with Phase -1?
- Does `workspace-baseline.json` exist and match the final RUN_ID?
- Was any previous mutable MESA storage reused?
- Was any previous mutable MESA_Data root reused?
- Could a stale Docker volume/container/network have affected results?
- Was any unknown user file deleted or modified?
- Were secret values exposed in logs/evidence?
- Do the frozen repository SHAs match the repositories actually tested?

Any unexplained contamination risk prevents `PROFILE_B_PASS_NATIVE`.

## VM bootstrap self-audit

Before final PASS ask:

- Did the final run use the canonical/recorded authoritative repository paths?
- Were all three origins verified?
- Was a non-canonical old checkout accidentally treated as authoritative?
- Did mutable SQLite/LanceDB/Kùzu/MESA_Data state live outside the Git repos?
- Does `bootstrap-layout.json` match the actual final RUN_ID paths?
- Was any unknown user data overwritten during normalization?
- If the canonical path was occupied, was the decision safely logged?

Any unexplained bootstrap/layout ambiguity prevents
`PROFILE_B_PASS_NATIVE`.

## Benchmark integrity self-audit

Before final PASS verify:

- Did any oracle/qrel/expected answer leak into a product/model request?
- Did TEST results influence tuning?
- Does certification SHA match the contract freeze?
- Do harness/scorer hashes match the freeze?
- Did all scorer canaries PASS?
- Were infra errors separated from ordinary misses?
- Was the runtime healthy before and after TEST?
- Were seeds/orderings/environment versions recorded?
- Did any dependency change after freeze?
- Did methodology semantics change after seeing results?
- Was evidence sealed before teardown?

Any unresolved false-PASS risk prevents `PROFILE_B_PASS_NATIVE`.

## Canonical MESA runtime lock self-audit

Before `PROFILE_B_PASS_NATIVE` verify:

- Was official scoring performed with effective Tier-3 Mode 0?
- Was `MESA_MODEL_ENABLED=true` effective?
- Did extraction still use real GPT-OSS?
- Did embeddings use real Nemotron with passage/query semantics?
- Did Docker/container runtime match the frozen host intent?
- Did any model/mode/provider setting change after TEST began?

Any unexplained runtime drift prevents PASS_NATIVE.

## Harness/GT false-result audit

Before final PASS ask:

- Did every required fact have exact source evidence?
- Could any GT item be materially ambiguous?
- Was every NO_ANSWER item audited against the whole frozen corpus?
- Did the scorer use exactly the frozen normalization version?
- Did executable harness tests/self-tests pass before official scoring?
- Did identity-map validation pass before retrieval scoring?
- Could oracle data have entered request construction?
- Did any scorer/harness semantic change occur after TEST began?

Any unresolved risk of harness-caused false PASS/false FAIL prevents
`PROFILE_B_PASS_NATIVE`.

## 8 GiB/OOM self-audit

Before `PROFILE_B_PASS_NATIVE` verify:

- Did the VM meet the 8 GiB RAM floor?
- Was resource telemetry active during every heavy phase?
- Did official TEST start with at least 2 GiB MemAvailable?
- Were WARNING/PRESSURE/CRITICAL events handled per document 34?
- Did cgroup/kernel OOM counters increase?
- Was any required container OOMKilled or unexpectedly restarted?
- Was heavy swap use disclosed?
- Was harness work reduced only in allowed pre-freeze ways?
- Was a genuine MESA OOM hidden by lowering the benchmark workload?

Any unexplained OOM/resource integrity risk prevents PASS_NATIVE.
