# All mandatory gates

No gate currently has a registered authoritative metric producer. This is explicitly represented by `PRODUCTION_METRIC_PRODUCERS = frozenset()`. Comparator functions and supplied status fields are not measurement producers. **All mandatory gates therefore remain UNVERIFIED, with empty observations/evidence.**

Thresholds in `config/profile-b-gates.json` are unchanged. Freeze materials and the config bytes pinned at transaction freeze acceptance are rechecked before gate evaluation. This does not validate the scientific meaning or completeness of a caller-prepared material inventory; unavailable producers prevent certification.

## B0: Clean exact code baselines and reproducible dependencies

**GATE ID:** B0

**METRIC SOURCE:** ci_actions_passed, clean_baseline_verified, dedicated_branch_verified, dependencies_reproducible

**ARTIFACT SOURCE:** baseline/CI/dependency evidence (producer unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B1: VM resource minimum and clean isolated run storage

**GATE ID:** B1

**METRIC SOURCE:** disk_min_gb, isolated_storage_verified, ram_min_gb

**ARTIFACT SOURCE:** isolated storage and host capacity observations (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B2: Real NVIDIA provider contract

**GATE ID:** B2

**METRIC SOURCE:** gpt_oss_completion_verified, nemotron_dim_verified, real_provider_contract_verified

**ARTIFACT SOURCE:** real provider preflight measurements (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B3: Production Docker config parity

**GATE ID:** B3

**METRIC SOURCE:** docker_config_parity, frozen_provider_parity

**ARTIFACT SOURCE:** Docker/provider parity evidence (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B4: MESA_Data raw integrity, canonicalization, and parsing coverage

**GATE ID:** B4

**METRIC SOURCE:** eligible_document_count, encoding_canonical_verified, raw_integrity_verified

**ARTIFACT SOURCE:** corpus parsing and raw integrity evidence (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B5: Hash-bound H1 human approval of corpus and delivery permission

**GATE ID:** B5

**METRIC SOURCE:** delivery_permission_granted, h1_approval_hash_bound

**ARTIFACT SOURCE:** hash-bound H1 approval (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B6: Native MESA_Data to MESA live contract canary passes

**GATE ID:** B6

**METRIC SOURCE:** canary_passed, no_bridge_substitution

**ARTIFACT SOURCE:** native live canary evidence (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B7: Full native delivery reaches terminal COMMITTED state

**GATE ID:** B7

**METRIC SOURCE:** chunk_mapping_proven, delivery_terminal_committed, undelivered_chunk_count

**ARTIFACT SOURCE:** terminal delivery and mapping evidence (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B8: Restart persistence and idempotent republish behavior

**GATE ID:** B8

**METRIC SOURCE:** idempotent_republish_proven, restart_persistence_proven

**ARTIFACT SOURCE:** restart/republish observations (unavailable)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B9: Isolation and ACL negative scope tests pass

**GATE ID:** B9

**METRIC SOURCE:** cross_tenant_scope_leakage, isolation_acl_passed

**ARTIFACT SOURCE:** scope/ACL observations (WAIT phase 7)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B10: Frozen TEST retrieval metrics meet thresholds

**GATE ID:** B10

**METRIC SOURCE:** answerable_mrr, answerable_recall_at_5, rel_complete_evidence_at_5, single_hop_recall_at_5, tenant_leakage

**ARTIFACT SOURCE:** scoring-summary.json + scoring-report.json; frozen GT join unavailable

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B11: Real Kùzu graph origin and causal ON/OFF contribution

**GATE ID:** B11

**METRIC SOURCE:** graph_capability_operational, graph_causal_ablation_proven, graph_provenance_verified, graph_rel_contribution_count

**ARTIFACT SOURCE:** paired graph ON/OFF evidence (WAIT phases 8/9)

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B12: Context-only answer grounding and abstention thresholds met

**GATE ID:** B12

**METRIC SOURCE:** answerable_pass_rate, fabricated_evidence_chunk_ids, no_answer_pass_rate, unsupported_material_claim_rate

**ARTIFACT SOURCE:** scoring-summary.json + scoring-report.json; exact context join unavailable

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B13: No OOM/Killed/catastrophic resource failure

**GATE ID:** B13

**METRIC SOURCE:** catastrophic_resource_failure, oom_killed_count, resource_usage_recorded

**ARTIFACT SOURCE:** health-pre/post-test.json + resource-telemetry.jsonl + resource-pressure-events.jsonl; measurement provenance unavailable

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults

## B14: Evidence integrity and hash verification passes post-freeze

**GATE ID:** B14

**METRIC SOURCE:** evidence_integrity_verified, post_freeze_mutations

**ARTIFACT SOURCE:** freeze/raw/index verification; complete cross-stage producer unavailable

**DERIVED INTERNALLY:** NO verified metric producer; transaction derives UNVERIFIED internally

**CALLER OVERRIDE POSSIBLE:** NO for a PASS claim; supplied metrics/evidence are not adopted

**EVIDENCE HASHED:** No authoritative gate evidence exists. Raw/scoring/freeze/index inputs have the checked bindings described in FINDINGS.md.

**RUN-BOUND:** No gate measurement accepted; underlying raw/oracle/score identity checks enforced

**MISSING DATA BEHAVIOR:** UNVERIFIED; mandatory non-PASS blocks verdict and finalization

**THRESHOLD SOURCE:** Unchanged config/profile-b-gates.json; no threshold-equivalent defaults
