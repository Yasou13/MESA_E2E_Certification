# MESA E2E Profile B Certification Coherence
# Independent Audit & Repair Report

Date: 2026-10-07

## 1. Repository / Branch / SHA

- Repository: `MESA_E2E_Certification`
- Baseline authoritative `origin/main`: `84b17a2a3201086334da1b3c0576b1f18d6ba8f3`
- Branch: `fix/profile-b-certification-coherence`
- Repair commit: `b6f1a80919d014e5354a168bd2cb83c5e00a8454`
- The branch was created from an up-to-date, clean `origin/main` after fetch/prune.

## 2. Baseline Profile B Architecture

The sole official entrypoint is
`harness.qualification_runner.run_profile_b_qualification`. It verifies the
contract freeze, loads frozen scoring/scope authority, verifies runtime and
provider identities, creates a process-bound official execution session, and
runs a `CertificationTransaction` through bootstrap, freeze, raw execution,
raw sealing, oracle audit, scoring, gates, verdict, and optional release.

Raw MESA and answer-provider captures are registered to an ephemeral official
execution authority. The raw manifest is built only from registered captures.
The oracle/GT scorer runs only after raw sealing and a passing oracle audit.
Gate observations are recomputed from sealed artifacts; the verdict is derived
from the complete mandatory B0-B14 gate set.

At baseline, retrieval and answer execution were not one evidence transaction:
B10 sealed `POST /v4/memory/search` top-5, while B12 independently fetched
session context. B4-B8 also consumed sealed JSON values without requiring
current runner ownership.

## 3. Suspected Issues Re-Verified

### RAM contradiction

- Claim: the hard gate required 32 GiB while the active Profile B operating
  contract defined 8 GiB minimum and 12 GiB recommended.
- Source proof: baseline `config/profile-b-gates.json` versus agent-pack resource
  documents.
- Reproduction: B1 rejected an otherwise valid 8 GiB observation.
- Verdict: real P1 contract inconsistency; repaired.

### B10/B12 coherence

- Claim: B12 could use evidence outside the certified B10 top-5.
- Source proof: the baseline runner performed an independent session-context
  request after sealing search output.
- Reproduction: a deterministic transaction showed an item absent from sealed
  top-5 could appear in independently supplied context.
- Verdict: real BLOCKER-class false-PASS path; repaired.

### B4-B8 authenticity

- Claim: manually authored upstream measurement JSON could claim successful
  corpus/delivery/restart state.
- Source proof: baseline metric producers verified file seals and fields but not
  that B4/B6/B7/B8 were produced by the active official execution.
- Reproduction: a syntactically valid `COMMITTED` canary passed the metric
  producer without authoritative backing.
- Verdict: real BLOCKER-class false-PASS path. The false PASS is closed. A
  production MESA_Data collector is still absent; this is the remaining blocker.

### Provider/model contract

- Claim: official provider identity was duplicated and incompletely enforced.
- Source proof: B2/B3 contained provider/model literals while the runner did not
  compare frozen embedding and extraction authority with one canonical Profile
  B contract.
- Reproduction: frozen embedding/extraction drift was not rejected by the
  runner's pre-TEST provider check.
- Verdict: real P1 identity-coherence defect; repaired for the fields present in
  the current contract.

## 4. RAM Requirement Contract

The canonical machine-readable contract is
`config/profile-b-gates.json:official_contract.resources`:

- minimum RAM: 8 GiB (hard B1 threshold);
- recommended RAM: 12 GiB (guidance, not a hard threshold);
- minimum free disk: 30 GiB (hard B1 threshold).

Gate loading now fails if B1's RAM or disk threshold drifts from this contract.
Boundary, below-boundary, recommendation, consistency, and missing-evidence
tests are present.

## 5. B10 Retrieval Contract

Official retrieval uses the frozen query, native session, frozen primary
dataset, and canonical `top_k = 5`. The normalized capture records response
hash, ordered rank, candidate ID, evidence/assertion ID, MESA chunk ID,
document ID, exact bounded evidence text, origins, scores, scope, and graph
paths. More returned candidates than the request limit is rejected.

## 6. B12 Context / Answer Contract

The official answer lane no longer performs an independent session-context
lookup. `build_sealed_retrieval_context` deterministically renders JSON-lines
blocks from the normalized sealed retrieval candidates. It applies the frozen
context policy and a conservative byte budget, retaining an inclusion or
`token_budget` rejection decision for every ranked candidate. Empty retrievals
must receive explicit frozen tenant/agent scope.

The answer capture binds the exact context, context hash, retrieval response
hash, ordered allowed evidence set, candidate provenance table, prompt hashes,
exact provider request/response, provider/model identity, and final citations.

## 7. B10 → B12 Evidence Binding

The enforced invariant is:

`answer_context_evidence_ids ⊆ sealed_top5_source_chunk_ids`

Additionally, the scorer requires exact equality for the sealed retrieval
response hash and ordered allowed set, and exact candidate-by-candidate
provenance equality for rank, IDs, origins, source text, and document identity.
An omitted candidate requires the explicit `token_budget` reason. Rank 6+ and a
hypothetical second retrieval cannot enter the official answer context.

## 8. B4-B8 Upstream Evidence Ownership

| Gate | Operation owner | Accepted official evidence | Run/hash binding | Result |
|---|---|---|---|---|
| B4 | MESA_Data corpus pipeline | Current-session `corpus_integrity` derived artifact plus recomputed raw/canonical hashes | execution ID, run ID, artifact SHA | Fail-closed, collector absent |
| B5 | Human H1 approval | Externally signed-off approval whose whole-file SHA equals frozen upstream authority | freeze SHA, run ID, release/selection hashes | Enforced |
| B6 | Native MESA_Data publisher + MESA | Current-session `native_canary` derived artifact | execution ID, run ID, artifact SHA, required mutation/chunk/count fields | Fail-closed, collector absent |
| B7 | Native full delivery | Current-session `delivery_evidence` derived artifact | execution ID, run ID, artifact SHA, exact planned/delivered set | Fail-closed, collector absent |
| B8 | MESA restart and MESA_Data republish | Current-session `restart_idempotency` derived artifact | execution ID, run ID, artifact SHA, before/after/count assertions | Fail-closed, collector absent |

A hand-authored, stale, foreign-run, or changed-after-registration JSON artifact
cannot now produce an official PASS. However, this repository contains no
production collector that calls the MESA_Data product path, observes the live
authoritative state, writes the required B4/B6/B7/B8 artifacts, and registers
their source captures with `OfficialExecutionSession`. There is also no
MESA_Data checkout in the audited workspace from which that contract could be
implemented and verified. Therefore a fresh run will truthfully block/unverify
these gates rather than falsely pass.

## 9. Provider / Model Contract

The frozen official values now come from one canonical configuration:

- embedding provider: `openai_compatible`;
- embedding endpoint: `https://integrate.api.nvidia.com/v1`;
- embedding model: `nvidia/nemotron-3-embed-1b`;
- embedding dimension: 2048;
- document/query input roles: `passage` / `query`;
- extraction provider/model: `openai_compatible` / `openai/gpt-oss-20b`;
- extraction language: `tr`;
- extraction minimum max tokens: 4096;
- answer provider/model: `openai_compatible` / `openai/gpt-oss-20b`.

The answer authority separately freezes prompt, instruction, request-parameter,
transport, and retry-policy hashes already present in the transaction. Wrong
provider, endpoint, model, dimension, role, or extraction identity fails before
TEST execution.

## 10. Freeze / Oracle Integrity

The audit confirmed:

- thresholds, GT/qrels, normalization, identity map, scorer sources, prompts,
  provider settings, and relevant harness sources are freeze-bound;
- the canonical Profile B contract is required as a frozen threshold material;
- TEST raw artifacts are sealed before oracle scoring;
- scorer version/hash and raw-manifest hash are checked during scoring/gates;
- threshold, qrel, prompt, provider, raw, or score mutation is rejected;
- verdict derivation uses the complete deterministic mandatory gate registry.

No new TEST-to-threshold, TEST-to-qrel, or TEST-to-prompt mutation path was
found.

## 11. B0-B14 Gate Audit

All fifteen mandatory gate IDs have concrete producers and deterministic
threshold evaluation. B0-B3 validate baseline/resources/providers; B4-B8 cover
the upstream corpus/delivery chain; B9 scope isolation; B10 sealed retrieval;
B11 graph provenance and paired ablation; B12 answers; B13 resources; B14 final
integrity. Missing producer evidence becomes BLOCKED/UNVERIFIED, never PASS.

The only material readiness gap is the absent production collector for the
runner-owned B4/B6/B7/B8 inputs described above.

## 12. False-PASS Attack Matrix

| Attack | Result |
|---|---|
| Zero workload / empty TEST | Rejected |
| Fake metrics or missing mandatory gate | Rejected |
| Missing/changed raw seal | Rejected |
| Threshold, qrel, prompt, or provider drift after freeze | Rejected |
| Oracle access before sealing / oracle leakage | Rejected |
| Cross-run or stale official artifact | Rejected |
| Hand-authored `COMMITTED` upstream JSON | Rejected in official mode |
| Rank-6/second-retrieval evidence in top-5 answer lane | Rejected |
| Context evidence ID outside sealed set | Rejected |
| Unexplained context-budget omission | Rejected |

The audited production code contains no qualification-query-ID-specific branch.
The 80-query TEST remains qualification/regression data, not a hidden holdout.

## 13. Defects Found

1. P1 — B1 resource contradiction. Root cause: duplicated hard threshold.
   Repaired with a canonical resource contract and boundary tests.
2. BLOCKER — independently retrieved answer context. Root cause: B10 and B12
   were separate evidence transactions. Repaired by deterministic sealed top-5
   context construction, provenance binding, and adversarial tests.
3. BLOCKER — upstream self-attestation false PASS. Root cause: official metric
   producers accepted sealed values without active execution ownership. False
   PASS is repaired by runner-owned derived-artifact verification. End-to-end
   collection remains incomplete because no authoritative MESA_Data collector
   exists in this repository/workspace.
4. P1 — provider identity fragmentation. Root cause: literals in producers and
   missing runner validation. Repaired with the frozen canonical provider
   contract and drift tests.

## 14. Files Changed

- Canonical contract and docs: `config/profile-b-gates.json`,
  `config/README.md`, `harness/README.md`,
  `contracts/WAIT_FOR_MESA_PHASE_10.md`.
- Runtime/integrity code: `harness/gates.py`, `harness/mesa_adapters.py`,
  `harness/artifacts.py`, `harness/answer_execution.py`,
  `harness/execution_provenance.py`, `harness/official_scoring.py`,
  `harness/metric_producers.py`, `harness/qualification_runner.py`.
- Regression coverage: the corresponding gate, adapter, scoring, runner,
  provider, HTTP, metric-producer, and adversarial test modules.

## 15. Commits

- `b6f1a80919d014e5354a168bd2cb83c5e00a8454` —
  `fix(profile-b): harden certification evidence coherence`
- A final documentation/audit commit records this report and post-commit lint
  cleanup.

## 16. Focused Test Results

- RAM/retrieval/upstream/provider/freeze/gate/runner adversarial selection:
  83 passed.
- Optimized harness self-test: 17/17 passed.
- Critical Ruff `F`/`E9` checks on every changed Python file: passed.

## 17. Full Regression Results

- Full pytest, including local HTTP integration: 518 passed in 12.18 seconds.
- Agent-pack checksum/membership: passed.
- Secret scan: passed.
- Tracked JSON/JSONL validation: passed.
- Python compileall: passed.
- `uv lock --check`: passed (14 packages resolved).
- `git diff --check`: passed.
- Full repository Ruff is not clean: 343 pre-existing style/lint findings were
  observed across the repository. Critical `F`/`E9` checks for changed files
  were cleaned and pass.
- Black 21.12b0 reports 11 touched files would be reformatted; the repository
  does not currently enforce a Black configuration and broad unrelated
  reformatting was intentionally not mixed into this repair.
- Mypy is not installed or declared in the locked development dependencies, so
  no native mypy run exists.

## 18. Documentation Consistency

Active documentation now agrees on 8 GiB minimum / 12 GiB recommended RAM,
sealed top-5 answer context, and the selected provider identities. The legacy
session-context adapter remains only for scope probes and backward-compatible
non-official captures; it is not an admissible official answer-context source.

## 19. Remaining Risks

One real Profile B integrity/readiness risk remains: implement and verify a
small production collector at the MESA_Data/MESA boundary that directly
observes B4, B6, B7, and B8 state, persists its raw observations inside the
current official capture, and registers the derived measurements with the
active execution session. Until that exists, the repaired harness correctly
refuses an official PASS for these gates.

## 20. Ready for Fresh Profile B Run?

NO — the runner-owned authoritative MESA_Data collector for B4/B6/B7/B8 is
absent. A fresh run may safely start for diagnostic/fail-closed validation, but
cannot produce a complete Profile B PASS through the current official runner.

MESA_E2E_PROFILE_B_HARNESS_REPAIR_INCOMPLETE
