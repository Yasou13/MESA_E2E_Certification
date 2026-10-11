# Adversarial Attack Matrix

Sonuç kodları: **REJECT** = exception/transaction failure, **FAIL** = hard gate/score failure, **UNVERIFIED/BLOCKED** = kanıt yetkisi yok; hiçbir vakada PASS yoktur. Focused ve tam suite sonuçları GREEN'dir.

| ID | Saldırı | Beklenen/gerçek sonuç | Kanıt testi |
|---|---|---|---|
| A01 | Freeze sonrası threshold değiştir | REJECT/INVALIDATED | `test_pre_vm_adversarial.py::test_lowered_gate_threshold_rejected_by_finalizer` |
| A02 | qrels/gold değiştir | REJECT (frozen material hash) | `test_c1_freeze_fail_closed.py`, `test_gt_governance.py::test_structural_validator_rejects_duplicates_bad_sources_and_qrel_drift` |
| A03 | prompt'u freeze sonrası değiştir | REJECT (prompt SHA mismatch) | `test_official_scoring_transaction.py`, `test_provider_execution_reliability.py::test_freeze_drift_rejects_differing_retry_policy` |
| A04 | provider digest/repo SHA mismatch | REJECT | `test_profile_b_provider_contract.py::test_answer_contract_same_tag_wrong_digest_fails`, `test_pre_vm_adversarial.py::test_qualification_runner_rejects_code_drift` |
| A05 | başka RUN_ID'den kanıt kopyala | REJECT | `test_b4_b8_attack_matrix.py::test_artifact_with_wrong_run_id_fails_closed`, `test_pre_vm_adversarial.py::test_adversarial_raw_lineage_stale_raw_from_other_run_rejected` |
| A06 | unsealed retrieval item context'e ekle | REJECT | `test_b10_b12_context_invariants.py::test_case_6_context_outside_sealed_set_fails_closed`, `test_comprehensive_repair_regressions.py::test_context_render_rejects_contamination_despite_valid_ids` |
| A07 | resmi retrieval yerine replay/mock | REJECT/BLOCKED | `test_f3_no_synthetic_pass_artifacts.py`, `test_trust_root_closure.py` |
| A08 | elle COMMITTED proof ekle | UNVERIFIED/REJECT | `test_b4_b8_attack_matrix.py::test_b6_fabricated_committed_json_fails_closed` |
| A09 | H1 signature/hash forge et | REJECT/FAIL | `test_metric_producers.py` B5 vakaları, `test_trust_root_closure.py` |
| A10 | raw manifest veya raw artifact boz | REJECT | `test_final_integrity_adversarial_audit.py::test_a06_raw_manifest_mutated_after_audit_rejected`, `test_b4_b8_attack_matrix.py::test_evidence_modified_after_seal_fails_closed` |
| A11 | raw seal öncesi score et | REJECT | `test_c8_transaction.py`, `test_independent_boundaries.py` phase-order vakaları |
| A12 | oracle/fact IDs provider request'e sızdır | REJECT çağrıdan önce | `test_mesa_adapters.py::test_phase10_rejects_fact_id_prompt_before_provider_call`, nested parameter parametrizasyonu, `test_comprehensive_repair_regressions.py::test_oracle_audit_rejects_fact_id_schema_or_prompt_tokens` |
| A13 | yanlış tenant/time/repealed citation | FAIL/REJECT | `test_phase7_scope_collector.py`, `test_pre_vm_adversarial.py` Phase-7 scope vakaları |
| A14 | doğru citation + yanlış cevap | FAIL | `test_comprehensive_repair_regressions.py::test_wrong_claim_with_valid_citation_still_fails_without_fact_ids` |
| A15 | malformed/empty/partial model JSON | REJECT/FAIL | `test_provider_execution_reliability.py::test_response_parser_schema_violation`, empty/non-string/missing choices vakaları |
| A16 | relational evidence group'lardan birini atla | MISS/PARTIAL, PASS değil | `test_answer_scorer_v2.py::test_all_required_facts_must_be_satisfied`, `test_retrieval_scorer` kapsamındaki relational testler |
| A17 | timeout ve partial-run restart | infrastructure failure/retry exhaustion | `test_provider_execution_reliability.py::test_repeated_transport_timeout_exhaustion`, `test_repeated_length_exhaustion_fails_closed` |
| A18 | provenance/HMAC'i boz | REJECT | `test_trust_root_closure.py`, `test_b4_b8_attack_matrix.py::test_evidence_modified_after_seal_fails_closed` |
| A19 | duplicate/reorder candidates ile MRR şişir | REJECT | `test_comprehensive_repair_regressions.py::test_context_builder_rejects_rank_or_identity_ambiguity`, `test_independent_retrieval_and_freeze.py` |
| A20 | interrupted write/resume mismatch | REJECT/immutable conflict | `test_c8_transaction.py`, `test_artifacts` kapsamı, `test_provider_execution_reliability.py::test_request_identity_hash_invariant_across_attempts` |
| A21 | rank-6/8 rescue veya ikinci retrieval | REJECT | `test_comprehensive_repair_regressions.py::test_context_builder_rejects_rank_six_rescue`, `test_b10_b12_context_invariants.py::test_case_4_second_retrieval_evidence_rejected` |
| A22 | boolean değeri sayısal eşik gibi kullan | FAIL | `test_comprehensive_repair_regressions.py::test_gate_comparison_rejects_bool_numeric_type_confusion` |
| A23 | doğru IDs ile context string'e ek talimat ekle | REJECT | `test_comprehensive_repair_regressions.py::test_context_render_rejects_contamination_despite_valid_ids` |
| A24 | unsupported extra claim / negation | FAIL veya UNRESOLVED | `test_final_integrity_adversarial_audit.py::test_a15_unsupported_one_token_material_claim`, `test_a16_unsupported_monetary_hallucination`, `test_a17_negated_required_fact` |

Tam attack seti ayrıca `tests/test_final_integrity_adversarial_audit.py` A01–A20, `tests/test_independent_attack_matrix.py`, `tests/test_pre_vm_adversarial.py` ve `tests/test_b4_b8_attack_matrix.py` içinde çalıştırılmıştır.

