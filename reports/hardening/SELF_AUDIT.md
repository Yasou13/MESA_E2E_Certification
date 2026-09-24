# Post-E8 Adversarial Self-Audit

STATUS: GREEN AFTER ONE REMEDIATION

The required eighteen attacks were executed against production harness paths,
not documentation-only fixtures. The focused regression command completed with
48/48 pytest cases passing, followed by 17/17 self-test cases under `python -O`.

| # | Attack | Result | Executable evidence |
|---:|---|---|---|
| 1 | Hard metric failure becomes final PASS | REPELLED | `test_each_retrieval_threshold_failure_blocks_final_pass` |
| 2 | Rank-1 entity gets a false HIT from deep gold provenance | REMEDIATED, REPELLED | `test_broad_entity_provenance_cannot_create_an_evidence_hit` |
| 3 | Matching keyword hides a missing required fact | REPELLED | `test_all_required_facts_must_be_satisfied` |
| 4 | Denial sentence contains the expected keyword | REPELLED | `test_denial_containing_required_keyword_cannot_pass` |
| 5 | Substantive answer appends `YETERSİZ KANIT` | REPELLED | `test_no_answer_requires_exact_marker_and_no_citations` |
| 6 | Regex is accidentally treated as literal, or vice versa | REPELLED | `test_regex_and_literal_modes_are_distinct` |
| 7 | Unknown identity becomes an ordinary product miss | REPELLED | `test_scorers_surface_unknown_identity_instead_of_product_miss` |
| 8 | Conflicting identity map loads successfully | REPELLED | `test_identity_rejects_conflicts_duplicates_unknowns_and_bad_rows` |
| 9 | Frozen material mutation remains valid | REPELLED | `test_contract_freeze_detects_material_and_repo_sha_drift` |
| 10 | Repository SHA drift remains valid | REPELLED | `test_contract_freeze_detects_material_and_repo_sha_drift` |
| 11 | Foreign RUN_ID artifact is silently accepted | REPELLED | `test_run_id_mismatch_fails_without_complete_reuse_authorization` |
| 12 | Missing mandatory evidence still permits PASS | REPELLED | `test_missing_artifact_unverified_gate_or_invalid_lifecycle_cannot_pass` |
| 13 | Oracle material enters a raw request and is scored | REPELLED | `test_raw_writer_preserves_leaked_request_for_audit_but_never_scores_it` |
| 14 | Scored output precedes immutable raw evidence | REPELLED | `test_scoring_before_raw_or_after_raw_mutation_fails_closed` |
| 15 | Incomplete final release is promoted | REPELLED | `test_finalizer_fails_atomically_when_artifact_missing_or_secret_present` |
| 16 | Optimization removes assertions and makes the self-test green | REPELLED | `.venv/bin/python -O -m harness.self_test` — 17/17 |
| 17 | Normalization config/code drift is ignored | REPELLED | `test_normalization_hash_assertion_and_repository_fixtures` |
| 18 | Historical run bytes are modified unnoticed | REPELLED | `test_historical_run_bytes_match_external_audit_manifest` |

## Remediation record

Attack 2 initially succeeded: `harness.retrieval_scorer` merged broad entity
provenance IDs with a result's first-class chunk ID, producing a rank-1 HIT when
only the nested debug/support provenance contained the gold chunk. The minimal
reproducer failed before the change. The scorer now validates the broad
provenance container but excludes it from scoring; only the first-class result
ID is normalized and graded. The reproducer now returns MISS and the full
optimized self-test remains green.

This remediation does not guess the future product response schema. The exact
matched-evidence adapter and versioned contract remain
`WAIT_FOR_MESA_PHASE_1`.

## False-positive challenge

The strongest remaining false-positive risk is an eventual integration adapter
misidentifying MESA's true evidence-level field, exact model-visible context, or
graph-origin semantics. That risk is material for a real certification and is
not resolved by this repository-only hardening loop. It is therefore explicitly
deferred under WAIT-1 through WAIT-4, and this work does not claim readiness for
a final Profile B v2 certification.
