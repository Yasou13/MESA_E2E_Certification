> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 27 — FINAL AGENT SELF-AUDIT

Before assigning a final verdict, run this adversarial self-review. The purpose is to catch a false PASS created by automation mistakes.

## A. Coherent-run check

- [ ] Every hard-gate PASS belongs to the same final RUN_ID.
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

