> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# MANIFEST — PROFILE B AUTONOMOUS AGENT PACK v3.1

## Purpose

This package is the repository-integrated operating contract for autonomous Profile B certification, built from the supplied MESA-main (14) and MESA_Data-main (32) source audits and hardened for a three-repository workflow.

## Files

- `00_START_HERE.md` — entry point/read order
- `01_MASTER_AGENT_PROMPT.md` — primary autonomous-agent contract
- `02_SYSTEM_MODEL_AND_NON_NEGOTIABLES.md` — system boundary and invariants
- `03_SOURCE_ARCHIVE_AUDIT_BASELINE.md` — exact supplied snapshot identities and discovered cross-repo/deployment risks
- `04_WORKSPACE_BRANCH_GIT_POLICY.md` — branch/commit/push/invalidation policy
- `05_ENVIRONMENT_SECRETS_DEPENDENCIES.md` — VM, secrets and locked dependency rules
- `06_PROFILE_B_OBJECTIVE_GATES_VERDICTS.md` — hard gates, thresholds and truthful verdicts
- `07_MESA_RUNTIME_PROVIDER_PREFLIGHT.md` — real NVIDIA + production-container preflight
- `08_MESA_DATA_QUALITY_REVIEW_RUNBOOK.md` — raw/canonical/encoding/coverage/release workflow
- `09_NATIVE_MESA_DATA_TO_MESA_CONTRACT.md` — native publisher semantic contract and live canary requirement
- `10_CORPUS_DESIGN.md` — deterministic corpus/DEV/TEST partition
- `11_HUMAN_H1_APPROVAL.md` — one hash-bound human gate
- `12_GROUND_TRUTH_FREEZE.md` — independent qrels/answer expectations and freeze
- `13_BENCHMARK_CONFIG_FREEZE.md` — anti-tuning freeze
- `14_EXECUTION_PHASES.md` — full phase machine
- `15_RETRIEVAL_SCORING.md` — provenance-based Recall/MRR/REL scoring
- `16_GRAPH_PROOF_AND_ABLATION.md` — real Kùzu origin + causal shadow ablation
- `17_FINAL_ANSWER_GENERATION_AND_GRADING.md` — context-only answers and deterministic grading
- `18_ISOLATION_IDEMPOTENCY_RESTART_PROVENANCE.md` — operational correctness hard checks
- `19_FAILURE_TRIAGE_REPAIR_RESTART.md` — autonomous repair policy
- `20_RESOURCE_AND_PROVIDER_BUDGETS.md` — runaway/cost/resource limits
- `21_EVIDENCE_MANIFEST_AND_INTEGRITY.md` — evidence structure and non-self-referential checksum design
- `22_LIVE_STATUS_TEMPLATE.md` — run status template
- `23_FINAL_REPORT_TEMPLATE.md` — final report template
- `24_QUICK_COMMAND_DISCOVERY_MAP.md` — low-token command/code discovery map
- `25_POST_FIX_PRELAUNCH_CHECKLIST.md` — final readiness checklist
- `26_EXPECTED_OUTPUTS_AND_ASSERTIONS.md` — semantic expected outputs per hard gate
- `27_FINAL_AGENT_SELF_AUDIT.md` — adversarial false-PASS audit before verdict
- `28_AUTONOMOUS_DECISION_DOCTRINE.md` — safe autonomous choice policy and decision journal for unspecified cases
- `MANIFEST.md` — this file
- `SHA256SUMS.txt` — generated integrity list for Markdown files; intentionally does not hash itself

## Key v3 design guarantees

1. removed final-report self-hash paradox;
2. native publisher is now a hard pass requirement; bridge is diagnostic-only;
3. identified the concrete supplied-archive MESA_Data↔MESA contract mismatch as a P0 revalidation item;
4. identified supplied MESA Compose provider-variable parity risk;
5. strict source-first ground-truth authoring and DEV/TEST separation;
6. benchmark configuration freeze before TEST;
7. deterministic H1 sample + all warnings/blockers;
8. uses existing MESA_Data parsing coverage system and requires real-corpus validation instead of duplicate machinery;
9. graph origin plus causal ON/OFF proof;
10. deterministic final-answer grounding rubric instead of same-model self-judging;
11. bounded provider calls/retries and resource tracking;
12. broader tenant/principal negative ACL tests;
13. remote model identity/revision limitation explicitly recorded;
14. one coherent final-run rule and full restart after code/harness/config changes;
15. autonomous unspecified-case decisions are bounded by a logged minimal/reversible decision doctrine;
16. qrels use source chunk IDs plus a frozen native identity map before TEST;
17. hash-bound H1 reuse is explicit and auditable;
18. final sanitized evidence bundles are promoted to Git-tracked `reports/releases/`.

## Repository integration

- The certification repository itself uses `cert/profile-b-e2e`.
- Certification runtime artifacts use repository-relative `runs/`, `evidence/`, `datasets/runtime/`, and `reports/generated/` locations.
- MESA and MESA_Data remain separate repositories and are discovered rather than hard-coded.
- Any executable certification-logic change invalidates an active run just like a product code change.
- The numbered documents are read strictly in order; no numeric gaps are intentional execution jumps.

## Integrity

Run from this directory:

```bash
sha256sum -c SHA256SUMS.txt
```

The checksum file is external to the Markdown documents to avoid circular/self-hash designs.


- `29_WORKSPACE_HYGIENE_AND_ISOLATION.md` — Phase -1 VM/workspace inventory,
  historical-state isolation, Docker hygiene, clean RUN_ID runtime and
  non-destructive cleanup policy.

- `30_VM_BOOTSTRAP_AND_CANONICAL_WORKSPACE_LAYOUT.md` — mandatory fresh/restored
  VM bootstrap, canonical `$HOME/mesa-cert` filesystem, repository normalization,
  RUN_ID storage layout and bootstrap evidence.

- `31_BENCHMARK_INTEGRITY_FREEZE_DETERMINISM_AND_FINALIZATION.md` — oracle
  isolation, complete contract freeze, deterministic environment manifest,
  scorer canaries, pre/post health snapshots, supply-chain rules and safe
  finalization/teardown.
