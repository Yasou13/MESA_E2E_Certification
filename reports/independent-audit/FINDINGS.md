# Reproduced findings

A fixed integrity bypass does not imply a working certification producer. IA-02/03/05/12 are fixed by withholding PASS until verified producers exist.

## IA-01 — Oracle surfaces could overwrite sealed raw inputs

**FINDING ID:** IA-01

**AUDIT LAYER:** 5

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** CertificationTransaction.execute_oracle_audit

**ROOT CAUSE:** Dictionary update let caller replace the raw path with clean content.

**WHY EXISTING TESTS MISSED IT:** Only empty or unrelated supplemental surfaces were tested, not a colliding raw path.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_audit.py::test_oracle_surface_collision_cannot_hide_raw`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/transaction.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_audit.py::test_oracle_surface_collision_cannot_hide_raw

**FAILED BEFORE FIX:** YES

**FIX:** Separate sealed_raw and supplemental namespaces; neither overwrites the other.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 49fb327537a4e99c68efa024a4b5e052079297b1

## IA-02 — Unbound scoring and invented population metrics

**FINDING ID:** IA-02

**AUDIT LAYER:** 6, 7, 8, 12

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** CertificationTransaction.execute_scoring

**ROOT CAUSE:** Raw retrieval fell through to perfect recall/MRR; answer vocabulary checks ignored frozen GT; caller scoring_fn could supply PASS; absent lanes inherited metrics.

**WHY EXISTING TESTS MISSED IT:** Fixtures called arbitrary scoring callbacks and treated status labels as official scoring.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_audit.py::test_empty_retrieval_response_is_not_scored_as_hit tests/test_independent_audit.py::test_custom_scorer_cannot_force_pass`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/transaction.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_audit.py::test_empty_retrieval_response_is_not_scored_as_hit; test_independent_audit.py::test_custom_scorer_cannot_force_pass

**FAILED BEFORE FIX:** YES

**FIX:** Remove synthetic scoring paths. Persist UNVERIFIED items with empty metrics while the verified frozen GT/runtime adapter is unavailable. Ignore alternate records and scoring callbacks.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 49fb327537a4e99c68efa024a4b5e052079297b1

## IA-03 — Caller metrics and unrelated paths passed mandatory gates

**FINDING ID:** IA-03

**AUDIT LAYER:** 9

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** CertificationTransaction.execute_gate_evaluation

**ROOT CAUSE:** Thirteen gates adopted caller metrics directly; path existence and fallback paths substituted for measured evidence.

**WHY EXISTING TESTS MISSED IT:** Coverage concentrated on B10/B12; happy fixtures supplied every other passing observation.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_audit.py::test_all_gate_metrics_are_authoritative tests/test_independent_audit.py::test_threshold_change_rejected_before_gate_evaluation`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/transaction.py; harness/gates.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_audit.py::test_all_gate_metrics_are_authoritative; test_independent_audit.py::test_threshold_change_rejected_before_gate_evaluation

**FAILED BEFORE FIX:** YES

**FIX:** Return explicit UNVERIFIED results for gates without authoritative producers, with no observations or evidence. Reverify freeze and reject changed threshold bytes.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 49fb327537a4e99c68efa024a4b5e052079297b1

## IA-04 — Health phase manufactured PASS without measurements

**FINDING ID:** IA-04

**AUDIT LAYER:** 12, 13

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** CertificationTransaction.execute_health_verification

**ROOT CAUSE:** Absent health_payload defaulted to PASS and wrote a provider preflight artifact without checking health or telemetry.

**WHY EXISTING TESTS MISSED IT:** Integration fixtures supplied status-only files or accepted the default.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_audit.py::test_health_requires_measurements`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/operations.py; harness/transaction.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_audit.py::test_health_requires_measurements

**FAILED BEFORE FIX:** YES

**FIX:** Read typed pre/post health and resource samples/events; recompute health/resource status. Missing measurements are UNVERIFIED. Do not synthesize provider evidence.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 49fb327537a4e99c68efa024a4b5e052079297b1

## IA-05 — Placeholder bundle could be promoted as PASS

**FINDING ID:** IA-05

**AUDIT LAYER:** 10, 12, 13

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** finalize_release

**ROOT CAUSE:** Finalizer accepted caller-selected mandatory registry and status-only artifacts without authoritative metric producers.

**WHY EXISTING TESTS MISSED IT:** Nominal successful finalizer fixtures were fake PASS JSON, often with one gate.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_audit.py::test_placeholder_pass_bundle_is_rejected`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/finalizer.py; harness/gates.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_audit.py::test_placeholder_pass_bundle_is_rejected

**FAILED BEFORE FIX:** YES

**FIX:** Require exact B0-B14 registry for PASS and reject certification while mandatory producers are unverified. Keep non-PASS evidence archiving available.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 49fb327537a4e99c68efa024a4b5e052079297b1

## IA-06 — Real evidence index hashes were not checked against files

**FINDING ID:** IA-06

**AUDIT LAYER:** 11

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** build_evidence_index → finalize_release

**ROOT CAUSE:** Finalizer verified the digest list hash but never read the indexed evidence bytes; empty indexes also passed.

**WHY EXISTING TESTS MISSED IT:** Producer integration tests checked only that a bundle existed.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_audit.py::test_real_index_mutated_artifact_rejected_by_finalizer tests/test_independent_revalidation.py::test_nonpass_archive_does_not_mask_evidence_mutation`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/finalizer.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_audit.py::test_real_index_mutated_artifact_rejected_by_finalizer; test_independent_revalidation.py::test_nonpass_archive_does_not_mask_evidence_mutation

**FAILED BEFORE FIX:** YES

**FIX:** Require a nonempty complete index and verify every confined referenced file against its hash before promotion. A non-PASS archive regression isolates this check from the PASS blocker.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 49fb327537a4e99c68efa024a4b5e052079297b1

## IA-07 — Unchecked extra claims and word overlap false-PASS

**FINDING ID:** IA-07

**AUDIT LAYER:** 8

**SEVERITY:** P1

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** score_answer

**ROOT CAUSE:** First matching claim ended the fact loop; a second unsupported claim was never evaluated. Shared context vocabulary was treated as propositional support.

**WHY EXISTING TESTS MISSED IT:** Earlier tests appended new vocabulary to one claim; they did not add a second claim or reuse unrelated context words.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_answer_claims.py::test_every_claim_must_be_checked tests/test_independent_answer_claims.py::test_vocabulary_overlap_does_not_prove_support`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/answer_scorer.py; tests/test_answer_scorer_v2.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_answer_claims.py::test_every_claim_must_be_checked; test_independent_answer_claims.py::test_vocabulary_overlap_does_not_prove_support

**FAILED BEFORE FIX:** YES

**FIX:** Check every claim and require a complete source-linked proposition/span for deterministic support. Unproven paraphrases remain non-PASS; regex matching alone cannot establish support.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 4cdbc76739309f210dc6ef1656636209e186991e

## IA-08 — Mixed identified and unidentified records passed identity checks

**FINDING ID:** IA-08

**AUDIT LAYER:** 14

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** validate_run_id_consistency

**ROOT CAUSE:** One run_id anywhere satisfied JSONL file identity; JSON arrays similarly ignored unidentified rows.

**WHY EXISTING TESTS MISSED IT:** Tests checked a wrong explicit run_id and completely missing identity, not a mixture.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_record_identity.py::test_every_structured_record_requires_identity`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/evidence.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_record_identity.py::test_every_structured_record_requires_identity

**FAILED BEFORE FIX:** YES

**FIX:** Require identity per non-allowlisted record in JSON, JSONL and their gzip variants; also check conflicting JSONL metadata identity.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 7127d9eb2e1dd9d5125810762b7a76f2125e4c9b

## IA-09 — Semantically empty material/runtime identity accepted

**FINDING ID:** IA-09

**AUDIT LAYER:** 2

**SEVERITY:** P1

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** verify_contract_freeze

**ROOT CAUSE:** Valid sidecars and category labels could accompany empty bytes or an empty runtime identity.

**WHY EXISTING TESTS MISSED IT:** Tests covered missing lists/categories but not nonempty lists pointing to empty material.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_boundaries.py::test_semantically_empty_freeze_rejected`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/freeze.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_boundaries.py::test_semantically_empty_freeze_rejected

**FAILED BEFORE FIX:** YES

**FIX:** Reject empty material files in creation/verification and empty runtime identity in verification.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** aea56aa1dc33d801fc314d14d39092b2bfc89dde

## IA-10 — Lifecycle history corruption accepted by a later phase

**FINDING ID:** IA-10

**AUDIT LAYER:** 3

**SEVERITY:** P1

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** CertificationTransaction._require_phase

**ROOT CAUSE:** Phase ordering relied on a mutable counter without replaying lifecycle history.

**WHY EXISTING TESTS MISSED IT:** Tests called methods out of order, but did not clear lifecycle history at an otherwise valid phase.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_boundaries.py::test_lifecycle_corruption_blocks_oracle_phase`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/transaction.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_boundaries.py::test_lifecycle_corruption_blocks_oracle_phase

**FAILED BEFORE FIX:** YES

**FIX:** Compare completed phases with the phase prefix; replay transitions and require lifecycle status to match the phase. Counter-skip test now diagnoses the phase boundary directly.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** aea56aa1dc33d801fc314d14d39092b2bfc89dde

## IA-11 — Raw and oracle records accepted foreign run identity

**FINDING ID:** IA-11

**AUDIT LAYER:** 4, 5, 14

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** RunArtifactStore.compute_raw_manifest; _require_passing_oracle_audit

**ROOT CAUSE:** Checksums/manifests were checked without requiring raw and oracle run_id to equal the store run.

**WHY EXISTING TESTS MISSED IT:** Earlier tests mutated content without resealing, so checksum errors masked missing identity checks.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_boundaries.py::test_oracle_audit_must_match_run_identity tests/test_independent_boundaries.py::test_raw_run_identity_checked_before_oracle`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/artifacts.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_boundaries.py::test_oracle_audit_must_match_run_identity; test_independent_boundaries.py::test_raw_run_identity_checked_before_oracle

**FAILED BEFORE FIX:** YES

**FIX:** Validate raw object/run identity during manifest construction and oracle run identity before scoring.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** aea56aa1dc33d801fc314d14d39092b2bfc89dde

## IA-12 — Production verdict API trusted caller gate registry

**FINDING ID:** IA-12

**AUDIT LAYER:** 10

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** derive_production_verdict

**ROOT CAUSE:** A caller-selected B10-only registry and fabricated COMPLETED manifest produced PROFILE_B_PASS_NATIVE.

**WHY EXISTING TESTS MISSED IT:** Tests exercised the transaction wrapper or injected a failing gate; they did not invoke the public production verdict function with a reduced registry.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_boundaries.py::test_production_verdict_rejects_caller_gate_registry`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/verdict.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_boundaries.py::test_production_verdict_rejects_caller_gate_registry

**FAILED BEFORE FIX:** YES

**FIX:** Require exact B0-B14 registry and refuse a PASS claim without registered authoritative metric producers.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** aea56aa1dc33d801fc314d14d39092b2bfc89dde

## IA-13 — Oracle/score mutation after scoring accepted by gates

**FINDING ID:** IA-13

**AUDIT LAYER:** 5, 6, 9

**SEVERITY:** P0

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** CertificationTransaction.execute_gate_evaluation

**ROOT CAUSE:** Gate phase validated summary and raw manifest but not current oracle audit, score-report bytes/count, or scorer source hash.

**WHY EXISTING TESTS MISSED IT:** Tests mutated only the score summary or raw files.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_revalidation.py::test_gate_evaluation_revalidates_oracle_after_scoring tests/test_independent_revalidation.py::test_score_report_mutation_detected_by_gate_phase`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/transaction.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_revalidation.py::test_gate_evaluation_revalidates_oracle_after_scoring; test_independent_revalidation.py::test_score_report_mutation_detected_by_gate_phase

**FAILED BEFORE FIX:** YES

**FIX:** Revalidate passing oracle and exact audit hash, actual serialized score-report hash/count, and scorer hash before gates.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 5662b2fc5a6bd199b95bdf0bec80bd9e5cd639e6

## IA-14 — Evidence path aliases bypassed uniqueness

**FINDING ID:** IA-14

**AUDIT LAYER:** 11

**SEVERITY:** P1

**STATUS:** FIXED_FAIL_CLOSED

**REPRODUCED:** YES

**PRODUCTION PATH:** build_evidence_index

**ROOT CAUSE:** Duplicate detection compared strings, so artifact.json and ./artifact.json counted separately.

**WHY EXISTING TESTS MISSED IT:** Duplicate tests used identical path strings.

**REPRODUCTION:** Run `.venv/bin/python -m pytest -q tests/test_independent_revalidation.py::test_evidence_path_aliases_are_duplicates`. Original failures are in sweep-1/2/3-reproductions.txt.

**FILES CHANGED:** harness/evidence.py plus named regressions and directly affected test fixtures

**REGRESSION TEST:** test_independent_revalidation.py::test_evidence_path_aliases_are_duplicates

**FAILED BEFORE FIX:** YES

**FIX:** Require the supplied path to equal its confined canonical relative path.

**FOCUSED TEST:** PASS; named regressions rerun after fix

**INTEGRATION TEST:** PASS; transaction/finalizer tests included in full pytest

**FULL RE-AUDIT STATUS:** 306/306 full pytest and A1-A30 pass; runtime certification remains unavailable

**SECURITY/ISOLATION IMPACT:** Prevents untrusted or mismatched observations from becoming authoritative evidence.

**CERTIFICATION IMPACT:** Closes the reproduced false-PASS/evidence-integrity path; no certification issued.

**BACKWARD COMPATIBILITY:** Intentional fail-closed change: formerly accepted unproven inputs may now fail or remain UNVERIFIED.

**KNOWN LIMITATIONS:** No verified MESA runtime/GT join or mandatory metric producers. Exact proposition support is conservative; semantic paraphrases may remain unresolved.

**COMMIT SHA:** 5662b2fc5a6bd199b95bdf0bec80bd9e5cd639e6
