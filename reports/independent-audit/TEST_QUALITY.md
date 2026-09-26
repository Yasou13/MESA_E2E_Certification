# Test quality audit

STRONG: independent collision, post-score mutation, foreign-but-resealed artifact, mixed-row identity, and non-PASS evidence archive mutation regressions. Each reaches the named production boundary.

ADEQUATE: deterministic scorer fixtures, generic threshold comparisons, freeze shape/hash tests, and bundle byte-checksum checks. These prove local behavior, not certification.

WEAK: broad exception assertions and synthetic repository SHAs in older fixtures. They remain useful for API mechanics, but do not verify external repository/runtime identity.

FALSE_CONFIDENCE: successful transaction/finalizer fixtures that supplied caller metrics and status-only PASS artifacts; scorer tests that injected “official” callbacks; missing-artifact tests that depended on a synthetic passing health phase. These were replaced/retargeted to non-PASS assertions, real index producers and direct finalizer checks. The regex test now separates matching syntax from support determination.

33 existing test bodies were changed or renamed. This is a change inventory, not a claim that every changed test was false confidence. Important corrected tests include:

- `test_adversarial_self_audit.py::test_a03_missing_mandatory_frozen_material`
- `test_adversarial_self_audit.py::test_a12_real_evidence_index_producer_accepted_by_finalizer`
- `test_answer_scorer_v2.py::test_regex_and_literal_modes_are_distinct`
- `test_c2_gate_verdict_finalizer.py::test_c2_placeholder_conditions_cannot_certify`
- `test_c5_evidence_index.py::test_c5_01_real_producer_accepted_by_real_finalizer`
- `test_c8_transaction.py::test_failure_at_gate_evaluation_refuses_finalization`
- `test_c8_transaction.py::test_unverified_transaction_cannot_produce_release`
- `test_f2_artifact_derived_gate_metrics.py::test_2_caller_recall_is_unverified`
- `test_f2_artifact_derived_gate_metrics.py::test_8_caller_score_callback_is_not_authoritative`
- `test_f3_no_synthetic_pass_artifacts.py::test_1_missing_health_pre_test_fails_finalization`
- `test_f3_no_synthetic_pass_artifacts.py::test_2_missing_health_post_test_fails_finalization`
- `test_f3_no_synthetic_pass_artifacts.py::test_3_missing_determinism_manifest_fails_finalization`
- `test_f3_no_synthetic_pass_artifacts.py::test_4_missing_scorer_canaries_fails_finalization`
- `test_f3_no_synthetic_pass_artifacts.py::test_5_missing_graph_summary_fails_finalization`
- `test_f3_no_synthetic_pass_artifacts.py::test_6_missing_resource_summary_fails_finalization`
- `test_f3_no_synthetic_pass_artifacts.py::test_7_transaction_never_creates_fake_pass_placeholder`
- `test_f3_no_synthetic_pass_artifacts.py::test_8_status_only_placeholders_are_rejected`
- `test_f3_no_synthetic_pass_artifacts.py::test_9_artifact_with_pass_status_but_invalid_schema_rejected`
- `test_f4_unsupported_answer_claims.py::test_13_b12_gate_reflects_unsupported_claims`
- `test_f4_unsupported_answer_claims.py::test_14_caller_clean_scores_cannot_pass_b12`
- `test_final_integrity_adversarial_audit.py::test_a02_zero_score_certification_fails`
- `test_final_integrity_adversarial_audit.py::test_a07_alternate_caller_scoring_record_rejected`
- `test_final_integrity_adversarial_audit.py::test_a08_fake_gate_metrics_rejected`
- `test_final_integrity_adversarial_audit.py::test_a09_fake_gate_evidence_rejected`
- `test_final_integrity_adversarial_audit.py::test_a11_missing_health_pre_test_fails_finalization`
- `test_final_integrity_adversarial_audit.py::test_a12_missing_determinism_manifest_fails_finalization`
- `test_final_integrity_adversarial_audit.py::test_a13_missing_scorer_canaries_fails_finalization`
- `test_final_integrity_adversarial_audit.py::test_a14_synthetic_pass_placeholder_injected_rejected`
- `test_operations_finalizer.py::test_complete_release_is_checksums_verified_and_mutation_detected`
- `test_transaction_e2e_integration.py::test_t1_placeholder_transaction_remains_blocked`
- `test_transaction_e2e_integration.py::test_t6_fails_at_gate_evaluation_if_score_below_threshold`
- `test_transaction_e2e_integration.py::test_t11_fails_at_release_finalization_if_artifact_missing`
- `test_transaction_e2e_integration.py::test_t12_multi_lane_capture_does_not_invent_metrics`

71 new collected test cases: 14 first-sweep cases, 7 boundary cases, 30 A1-A30 cases, 4 third-sweep revalidation cases and 16 independent retrieval/freeze cases. One second-sweep counter-skip probe originally failed only because it received the wrong diagnostic; that is not counted as a newly reproduced PASS bypass.

No skipped/xfail tests were introduced. Positive finalizer packaging tests now explicitly archive a non-PASS result with a real nonempty evidence index; checksum PASS is not certification PASS.
