# MESA_E2E_Certification — Comprehensive Audit, Repair, and Independent Verification Loop

> **Execution scope:** `MESA_E2E_Certification` repository only.  
> **Goal:** Identify and repair verified certification correctness, integrity, reliability, and integration defects without weakening the official Profile B contract or fabricating PASS results.  
> **Working language:** English for code and technical analysis; prepare final human-readable findings in Turkish.  
> **Operational model:** An external development agent repairs/pushes the repository. The certification VM is a separate environment and must not be modified by this agent.

## 0. Non-negotiable mission

You are a senior software assurance engineer, Python test infrastructure engineer, and adversarial certification auditor. Perform a **repository-wide source-to-runtime audit**, reproduce issues with minimal deterministic tests, repair only independently verified defects, and establish that the harness measures the product rather than creating false PASS or false FAIL results.

This is **not** a mission to make Profile B pass. Genuine product failures must remain failures. The reference run `RUN-20261009T152914Z-profile-b-fresh` has a reported official verdict of `PROFILE_B_FAIL` and must remain immutable. We are repairing the **measurement apparatus**, not altering historical results, ground truth, qrels, thresholds, model responses, or MESA product behavior.

Treat prior audit narratives as **hypotheses**, not authoritative facts. The current checked-out source and the **actual frozen official run artifacts** outrank all prose reports. Verify claims at exact SHAs. In particular, a prior report misidentified B13/B14, and a later source audit could not access the original run artifacts. Never silently merge those conflicting accounts into one invented narrative.

## 1. Absolute safety and scope boundaries

1. Work in `MESA_E2E_Certification` **only**. You may inspect adjacent `MESA` and `MESA_Data` as **read-only dependencies** to establish API/data contracts. Do not edit or push them. List external changes as follow-up dependencies.
2. **Never** edit, recreate, overwrite, normalize, relabel, rescore, unseal, or delete an existing official run's `raw/`, freeze manifests, qrels, ground-truth, `verdict.json`, gate outputs, hashes, or provenance.
3. Do not lower, bypass, or dynamically adjust B0–B14 thresholds, scope restrictions, citation requirements, evidence gates, memory/disk requirements, or profile policy to improve the pass rate.
4. Do not tune prompts, scoring logic, search parameters, or model configuration against official frozen TEST or any hidden holdout. Use synthetic fixtures, isolated DEV data, and regression cases designed from *defect mechanisms*, not leaked target answers.
5. Do not expose hidden oracle `fact_id`, `required_facts`, expected answers, qrels, or TEST labels to the answer model, retrieval runtime, evidence selection, or pre-seal phase.
6. Do not substitute replay, mock, fabricated, externally supplied, or manually authored evidence as authoritative production observations. Test mocks may validate code behavior only and must be labeled tests.
7. Do not introduce a second unsealed retrieval, hidden context expansion, rank-8 rescue, or cross-scope evidence into answer generation.
8. Do not hide errors as warnings or default-to-PASS. Missing, corrupt, inconsistent, unauthorized, ambiguous, or unprovable evidence **fails closed**.
9. Do not run or expose a hidden holdout. Do not launch a new official Profile B on the development machine. An isolated **non-official** DEV integration smoke test is allowed if correctly labeled and not scored as certification.
10. Avoid overengineering: prefer localized changes, existing contracts and patterns, explicit invariant tests, and minimum additional abstractions.

## 2. Git discipline before any edit

1. Print repository root, origin URL (redact credentials), current branch, HEAD SHA, worktree status, Python and dependency versions, CI workflow inventory, and relevant docs.
2. `git fetch --all --prune`; inspect local/remote state without destroying work. If the tree is dirty, diverged, or contains untracked user changes, **STOP and report** instead of overwriting or stashing.
3. Identify the latest authoritative baseline. Create a new dedicated branch, suggested name `fix/profile-b-comprehensive-certification-hardening`, from the verified baseline. If work already exists on an equivalent repair branch, inspect its commits and coordinate rather than overwriting it.
4. Never use `git reset --hard`, `git clean -fd`, force-push, automatic merge, destructive checkout, secret leakage, or unauthorized branch modification.
5. Before each major change, record the failing reproduction. Commit each logically independent completed repair with a focused message. Push the repair branch only after verification; never automatically merge to `main`.
6. Record exact starting SHA, final SHA, upstream remote branch, and which fixes remain unmerged. The VM must later fetch **this exact reviewed SHA**, not assume fixes are on `main`.

## 3. Phase A — Establish the canonical certification contract

Map the actual repository layout and import graph before assuming file paths. Likely starting points (verify actual paths):

- `config/profile-b-gates.json`
- `harness/qualification_runner.py`, runner CLI/entrypoints
- `harness/metric_producers.py`, `harness/models.py`
- `harness/answer_execution.py`, `harness/answer_scorer.py`
- `harness/mesa_adapters.py`
- execution-session / provenance / artifact registry modules
- freeze, raw manifest, oracle-audit, scoring, gate evaluation, and verdict builders
- `tests/`, `agent-pack/`, `reports/`, `pyproject.toml`, lock files, CI workflows.

Construct a **source-of-truth map** with owner code path, input types, output types, version/hash policies, and entrypoints for:
`PREPARE → AUTHORIZE/H1 → FREEZE → EXECUTE → RAW_SEAL → ORACLE_AUDIT → SCORE → GATE_EVALUATE → FINAL_VERDICT`.

Map each canonical B0–B14 gate: name, frozen hard/soft rule, required fields, producer, provenance authority, preconditions, threshold, invalid/missing evidence treatment, and final verdict effects. **Do not use names/limits copied from the erroneous forensic report.** Confirm that B1 includes the actual RAM and disk conditions, B2 provider contract, B3 runtime parity, B4 corpus integrity, B5 H1 approval, B6 native canary, B7 delivery, B8 restart, B9 isolation, B10 retrieval, B11 graph causal ablation, B12 grounded answers, B13 stability, B14 tamper resistance—provided those names match the live frozen canonical contract. If they differ, document the precise source-backed differences, never change contracts to fit descriptions.

## 4. Phase B — Historical evidence reconciliation (strictly READ-ONLY)

Investigate the reported conflict for `RUN-20261009T152914Z-profile-b-fresh`:

- Report A: `8 PASS / 3 FAIL / 4 UNVERIFIED`, B13 stability, B14 tamper resistance.
- Report B: `6 PASS / 5 FAIL / 4 UNVERIFIED`, B13/B14 incorrectly characterized as fact-scoring gates.
- Discrepant SHA-256 for `verdict.json`, `gate-results.json`, and `retrieval-summary.json`; `contract-freeze.json` reportedly has the same hash.
- Reported answerable `Recall@5 = 0.50`, `MRR = 0.3131`, relational complete evidence `= 0`, answer pass rate `= 0`, no-answer pass `= 1.0`.

Locate **the exact sealed artifacts** where accessible. First verify identities, file hashes against the sealed manifest, source SHA, gate schema and freeze. Identify which reports are secondary derivatives or untrusted retellings. Report exact discrepancies and whether any historical artifacts were rewritten or merely independently reserialized. **Do not assume either explanation without byte evidence.**

If the sealed run and/or runtime stores are inaccessible, record `HISTORICAL_EVIDENCE_UNAVAILABLE` explicitly; do not reconstruct missing TEST traces from prose or an unrelated run. Continue source audit and synthetic regressions, but mark all historical per-query causal claims as unverified.

Store new reports and CSVs under a **separate audit output directory** outside official run trees. Do not change historical verdicts even if diagnostic rescoring exposes measurement flaws.

## 5. Phase C — Repository-wide inventory and static audit

Scan all active certification code paths, not only previously reported failures:

- configuration loading, precedence, environment override, defaults, schema validation, hidden fallbacks, CLI entrypoints;
- freezing/hash canonicalization, provider identity/digests, model/profile binding, repository SHAs, runtime identities;
- runner state machine, retries/resume, process crash, concurrency, timeouts, partial artifact writes and atomicity;
- metadata and citation identity, qrel ↔ retrieved evidence mapping, aliases, version/time filters, multi-hop evidence groups;
- real HTTP provider request/response capture, HTTP failure semantics and malformed JSON responses;
- canonical identity across source chunk, retrieval hit, model-visible chunk, citation and scorer;
- sandbox/path traversal and symlink safety, secret redaction, untrusted model outputs, file descriptor/resource cleanup;
- CI workflows, deterministic test fixtures, lockfile reproducibility, packaging/imports, type/static quality and documentation.

Tag every finding with `CONFIRMED`, `REPRODUCED`, `PARTIAL`, `UNVERIFIED`, or `NOT_AN_ISSUE`, severity `P0/P1/P2`, scope, and evidence. Distinguish harness defects from genuine MESA/MESA_Data/model/VM limitations.

## 6. Phase D — P0: Answer prompt ↔ schema ↔ scorer protocol

A previous audit reported an answer-generation prompt containing a JSON example with **`"claims": []`**, while the answer schema requires `claims: list[AnswerClaim]`, `AnswerClaim.fact_ids` nonempty when a claim exists, and the scorer matches oracle `required_facts` through the model-supplied `fact_ids`. Treat these as allegations until confirmed against the exact code and request captures.

Trace end-to-end:

`frozen answer authority → system_prompt → user_instruction/template → exact_provider_request.messages → raw provider text → JSON/Pydantic parse → AnswerClaim → supported_by/citations → required_facts matching → final status/reasons/aggregator`.

**Mandatory reproductions:**

1. A valid evidence-grounded answer with real citations and semantically complete legal facts is rejected solely because `claims=[]`.
2. An answer containing valid citations but a materially wrong fact must still fail.
3. An answer with fabricated citation IDs must fail.
4. Partial/ambiguous/conflicting evidence must not be falsely approved.
5. Valid insufficiency on a genuinely unanswerable question passes; unsupported confident answer fails.
6. A model cannot be required to guess or receive internal oracle fact IDs.
7. A malformed response, schema-violating claim, or ungrounded `supported_by` reference cannot silently pass.

Repair the **contract**, not the evidence. Preferred design: model outputs **ordinary natural-language atomic claims with explicit references to supplied visible evidence IDs**; independent post-seal scoring evaluates whether each frozen required proposition is correctly and sufficiently supported by allowed context. Do **not** assume that a cited chunk ID alone proves a proposition. Ensure this is deterministic and auditable to the extent defined by official methodology; for semantic ambiguity distinguish `UNRESOLVED`/review from `PASS` rather than inventing a permissive fuzzy threshold. Do not introduce a judge LLM without an explicit authorized, frozen, leak-safe methodology and proven need.

If the official contract currently uses non-public oracle `fact_ids` as model inputs, remove that dependency from generation. If grading uses oracle IDs **internally after sealing**, that is acceptable so long as matching is based on valid claims and evidence, not the model knowing secret identifiers. Preserve meaningful strictness for correctness, support, citation, scope, temporality, and abstention.

Define unambiguous statuses: `PASS`, `FAIL`, `UNRESOLVED` and their exact influence on metrics. Ensure zero required-fact and multiple-required-fact edge cases are tested. Refuse a shallow patch such as adding `claims` placeholders, requiring model to output oracle IDs, marking all nonempty answers as PASS, or changing `0/70` historical score in place.

Add focused mutation/adversarial regression tests so the original defect and tempting false-PASS workarounds cannot recur.

## 7. Phase E — P0: B4 / B6 / B7 / B8 official runner-owned provenance

Inspect the source ownership of `corpus_integrity`, `native_canary`, `delivery_evidence`, `restart_idempotency` and their exact canonical artifact names. Trace collection lifecycle and `_require_official_runner_owned` / `verify_derived_artifact` semantics.

Determine whether observations are missing because:
- the authoritative collectors do not exist;
- evidence was generated outside `OfficialExecutionSession`;
- the runner omitted `register_derived_artifact`;
- wrong artifact type/path/hash/session authority was used;
- evidence was captured before the relevant runtime state completed;
- an external MESA_Data integration boundary is unsupported.

Implement the **smallest correct runner-owned collectors/integration** necessary to observe live, real outcomes, register each artifact under the correct official session with supported provenance/HMAC, and verify before gates consume it. Do not merely register arbitrarily existing files or grant authority to user-created artifacts. A gate must prove what it claims:
- B4: real selected approved corpus, source integrity, encoding/canonicalization/coverage and count;
- B6: real native canary and absence of bridge/mock substitution;
- B7: selected release → exact MESA chunk mapping, terminal committed delivery and zero silent omissions;
- B8: real restart persistence and idempotent re-publish/replay without duplication or loss.

When reliable collection requires a feature in MESA or MESA_Data that cannot be implemented legitimately in this repo, output `EXTERNAL_DEPENDENCY` with exact missing API/contract, required owner and reproduction. **Do not fabricate a collector or weaken the gate.** Add tests proving false session, mutated bytes, stale reused artifact, wrong RUN_ID, missing producer, and forged provenance all fail closed.

## 8. Phase F — P0: B10 retrieval ↔ B12 answer-context binding

Verify against actual adapter code and captured request construction:

- The frozen official retrieval request is authorized, scope-constrained, bound to baseline `single` planner unless otherwise frozen, and takes the specified Top-K (historically reported Top-5). Do not expand it to 8/10 or rerun it to rescue misses.
- The answer model context contains **only** approved source evidence IDs from the same official sealed retrieval event and selected query identity.
- `model_visible_context_ids ⊆ official_retrieved_allowed_ids` and `model_cited_ids ⊆ model_visible_context_ids`.
- Physical source ID, citation ID, assertion ID and evidence span mappings are explicit. Invalid joins must not be resolved by guessing, relabeling or cross-tenant leakage.
- A Top-8 item cannot appear in the Top-5 model context; an out-of-scope/expired/repealed entity cannot be smuggled in by a second retrieval.
- Context packing respects the **frozen** token budget, truncates safely at evidence boundaries when required, preserves evidence identity and logs exact omissions; no silently corrupted strings or facts.
- Separate MESA `ContextBuilder` and the official E2E `build_sealed_retrieval_context` must not be confused in diagnosis.
- The official retrieval evidence and LLM requests must have traceable IDs/hashes, no oracle contamination, and correct query alignment.

Add anti-cheating tests for rank-8 rescue, swapped query IDs, duplicate IDs, misleading metadata, revoked allowed IDs, context injection, truncated evidence, and external citations. Any invariant break fails the run.

## 9. Phase G — B10 / B11 / B12 metric correctness and qrel semantics

Recompute metric formulas from controlled synthetic fixtures and inspect production implementation:

- `Recall@1/3/5`, MRR, nDCG where officially defined; rankings, ties, duplicate candidates, empty lists;
- qrel evidence granularity (chunk/assertion/span), source identity and version; multiple accepted equivalent evidence IDs;
- answerable vs no-answer denominators, missing output and timeout handling;
- relational complete evidence requiring **all** mandatory evidence groups, not a single group or mere graph activation;
- graph ON/OFF causal deltas, positive/neutral/harm samples, full scope equality, deterministic comparison;
- citation correctness, supported claim checking, fact completeness and distinct abstention categories;
- no grade credit for a lucky answer produced from external model knowledge when MESA failed to supply necessary proof;
- no grade inflation from reused evidence, lexical shortcuts, repeated citations, or cross-query reuse.

Never change qrels or numerical thresholds to make current baseline pass. Any discovered scoring formula error requires a narrowly scoped correction and independent regression proof; historical reports remain untouched.

## 10. Phase H — B0/B1/B2/B3/B5/B9/B13/B14 integrity and environment gates

Audit all remaining gates for both false PASS and false FAIL:

- **B0:** exact Git SHA, clean status, CI/test validity, dependency lock reproducibility;
- **B1:** physical RAM vs process/cgroup availability; disk bytes vs GiB; filesystem actually used; safe margin. Existing Profile B reportedly requires RAM >=8 GiB and disk >=30 GiB. Do not silently change units or lower requirements;
- **B2:** real Ollama provider proof, resolved immutable Magibu/Qwen digests, measured 768 dimension, normalization and no fallback;
- **B3:** live runtime configuration parity including API/auth/provider and Docker/combined profile equivalence as actually required;
- **B5:** H1 approval bound to the exact selected versions/release hashes, signed/authorized and before delivery;
- **B9:** tenant, dataset, agent, time, jurisdiction and repealed-version negatives; no silent scope leaks;
- **B13:** no catastrophic resource failure, telemetry authority, OOM/crash detection, resource time windows, bounded runtime;
- **B14:** immutable freeze, atomic raw sealing, manifest verification, unauthorized post-freeze mutation detection, SHA/identity validation.

Check ambiguous or conflicting capacity observations in prior reports (e.g. ~75 GiB vs 15.6 GB free) as **time/filesystem/host questions**, not as justification to weaken B1. Hardware capacity is a VM/operator dependency, not a code repair.

## 11. Phase I — Ollama inference and embedding contract

Confirm actual code supports Magibu 768d and Qwen `qwen3.5:9b-q4_K_M` via configurable endpoints with immutable resolved digests. Never hardcode a LAN IP, mutable `latest` tag as immutable identity, or API credentials. Test:

- correct `/api/embeddings`/`/api/embed` request contract as implemented, valid vector length/norm, query/document route distinctions where model supports them, no Nemotron-specific `input_type` applied to Magibu without proof;
- correct `/v1/chat/completions` request shape, frozen system and user prompts, structured answer schema, generation params and response-format compatibility;
- bounded timeout and explicit no-fallback behavior; network failure must be an infrastructure error, not an answer failure or success;
- model/provider retries cannot duplicate scored executions or mix model digests;
- capture real response content and model identity securely, redact secrets;
- reject incompatible vector space or configuration changes before official execution.

Do not invent that Magibu or Qwen is inherently bad based on the flawed historical answer score. Provider/model quality requires separate independent DEV qualification.

## 12. Phase J — State-machine, replay, integrity, and security adversarial tests

Build a defensible attack matrix; include at least:

1. alter threshold after freeze;
2. mutate qrels or gold answer;
3. mutate prompt after freeze;
4. mismatch provider digest or repo SHA;
5. copy evidence from different RUN_ID;
6. inject unsealed retrieval item into answer context;
7. replace official retrieval with replay/mock;
8. attach manually authored `COMMITTED` proof;
9. forge H1 signature/hash;
10. corrupt raw manifest/one raw artifact;
11. force score before raw seal;
12. leak oracle/fact IDs into model request;
13. wrong-tenant or wrong-time citation;
14. assert correct citation with false answer;
15. return malformed/empty/partial model JSON;
16. omit one required graph evidence group;
17. simulate provider timeout and partial-run restart;
18. tamper artifact provenance/HMAC;
19. duplicate/reorder retrieval candidates to inflate MRR;
20. cause interrupted atomic file write or resume mismatch.

Assert each attack produces the expected strict rejection, `UNVERIFIED`, or `FAIL` per official contract—not a PASS. Document exact test file, case ID, and output.

## 13. Phase K — Reproduction, repair loops, and limitations

Follow this loop for each P0, then P1, then P2:

`INSPECT → HYPOTHESIS → REPRODUCE RED → TRACE CAUSAL MECHANISM → SMALLEST FIX → POSITIVE TEST → NEGATIVE/ADVERSARIAL TEST → INDEPENDENT RECHECK → COMMIT`.

Try no more than three meaningful repair hypotheses per independent defect without stopping to explain the blocker. Never make broad speculative rewrites or weaken gates merely because a test fails.

Prefer targeted changes over a new scoring framework, opaque fuzzy judge, second retrieval engine, alternate oracle distribution mechanism, or widespread refactoring. Update documentation and schemas only as required by the verified fix. If public contracts must change, provide migration/version compatibility tests.

Classify test-environment deadlocks or filesystem restrictions as `ENVIRONMENT_BLOCKED` unless reproduced as production defects. Do not pretend a timeout is green.

## 14. Phase L — Verification and CI

Perform and record:

- focused regression tests per defect with original RED and final GREEN;
- entire repository test suite at the pinned dependencies;
- lint/format, type checking, import/packaging/CLI smoke, and dependency constraints where configured;
- frozen gate registry validation and contract snapshots;
- mocked adversarial cases and non-official DEV integration where available;
- negative tests with honest `FAIL`/`UNVERIFIED` decisions;
- read-only full-tree source review for insecure fallbacks, accidental test skips, threshold changes, silent scoring bypasses, and scope creep;
- diff against baseline, commit-by-commit audit, clean worktree, and CI status on pushed branch.

The previous report mentions `554/554` passing tests. That number is **not** proof that the repo is correct; reproduce the current actual total and inspect missing adversarial coverage. Never claim tests passed when they were skipped or blocked.

## 15. Mandatory acceptance criteria

Do not declare the repair complete unless all applicable criteria hold:

1. No known systematic false-FAIL caused by the prompt/claims/scorer interface; positive facts are validated **without oracle leakage**.
2. An unsupported or materially wrong answer with valid citations **cannot pass**.
3. An abstention on answerable evidence is evaluated according to the frozen contract, not automatically excused.
4. No unsealed, out-of-scope or separately re-retrieved evidence reaches the answer model.
5. B4/B6/B7/B8 produce genuine runner-owned observations or stay `UNVERIFIED` with a precisely reported external dependency.
6. B0–B14 gate names and thresholds derive from canonical frozen authority; B13 remains stability and B14 integrity if defined so by the target source.
7. Raw seal, oracle barrier, hash validation, session authority, and historical evidence immutability survive the attack suite.
8. All remaining authentic product misses, incomplete legal evidence and VM RAM failures **continue to FAIL**.
9. Full repo tests and relevant checks pass without skipped blockers, or give an honest incomplete verdict.
10. No official Profile B TEST rerun or holdout used to tune code.
11. Each implemented repair is committed, reviewed, pushed, and identified by exact SHA.

## 16. Required deliverables

Create, OUTSIDE any official run directory, at minimum:

- `reports/profile-b-comprehensive-repair/FINAL_AUDIT_AND_REPAIR_REPORT.md` (Turkish, detailed, readable, source-backed);
- `reports/profile-b-comprehensive-repair/FINDINGS_REGISTER.csv` (`ID`, component, P0/P1/P2, evidence, reproduction, old/new behavior, tests, commit, disposition);
- `reports/profile-b-comprehensive-repair/GATE_AUTHORITY_MATRIX.md` (B0–B14 true meanings/thresholds/collector/authority);
- `reports/profile-b-comprehensive-repair/ANSWER_CONTRACT_AND_ORACLE_AUDIT.md` (prompt/response/scorer mapping and positive + false-PASS tests);
- `reports/profile-b-comprehensive-repair/PROVENANCE_LIFECYCLE.md` (B4/B6/B7/B8 producer and session binding);
- `reports/profile-b-comprehensive-repair/RETRIEVAL_CONTEXT_INVARIANTS.md` (B10→B12 seals, ranks, citations, token budget);
- `reports/profile-b-comprehensive-repair/ATTACK_MATRIX.md` (all injection, tamper, false-PASS/FAIL tests);
- `reports/profile-b-comprehensive-repair/VERIFICATION_SUMMARY.md` (actual commands and results, skipped tests, CI status, review).

Reports must distinguish **observed**, **reproduced**, **inferred**, **unverified**, and **externally blocked**. Cite exact repo-relative source paths, relevant functions/line windows (as verified at HEAD), reproducer command, and error/output. Do not include secrets or ground-truth disclosures in public artifacts; use sanitized diagnostic fixtures and hashed identifiers if necessary.

## 17. Final external-agent handoff

Finish by displaying:

- final verdict;
- authoritative repository remote URL, baseline SHA, repair branch, final pushed SHA;
- all P0/P1 fixes by commit, with causal evidence;
- test counts and command outputs (PASS/FAIL/SKIP/NOT_RUN); CI link/status if verified;
- confirmed unchanged gates, thresholds, oracle barrier and historical official verdict;
- what remains owned by `MESA`, `MESA_Data`, or VM operator;
- exact VM instruction: fetch repair branch at **final SHA**, verify clean state and supported deployment, then run a **new fresh Profile B only after all external blockers are cleared**.

Use one final machine-readable verdict:

- `MESA_E2E_AUDIT_REPAIR_VERIFIED_AND_PUSHED`
- `MESA_E2E_AUDIT_VERIFIED_NO_REPAIR_NEEDED`
- `MESA_E2E_AUDIT_REPAIR_INCOMPLETE`
- `MESA_E2E_AUDIT_REPAIR_EXTERNAL_DEPENDENCY_BLOCKED`
- `MESA_E2E_AUDIT_REPAIR_PUSH_BLOCKED`

**Do not label a code repair as official Profile B certification.** The historical official result remains `PROFILE_B_FAIL`; only a wholly new independent run can create a new official result.
