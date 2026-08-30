> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 00 — START HERE

This folder is the complete operating contract for the autonomous Profile B agent. The intended operator is Antigravity CLI (or another shell-capable coding agent) running inside the certification VM.

## Mission in one sentence

Prove, with reproducible evidence, that **approved legal data produced by MESA_Data can be published through the native MESA_Data→MESA product path into the current MESA V4 runtime, retrieved correctly with real NVIDIA embeddings/LLM extraction, isolated by tenant, persistent/idempotent across restart, and used to produce grounded legal answers**.

Profile B is not a unit-test exercise and it is not a README compliance exercise. It is an evidence-producing black/gray-box integration certification.

## Read order — mandatory

Before running commands, read every file in this order:

1. `01_MASTER_AGENT_PROMPT.md`
2. `02_SYSTEM_MODEL_AND_NON_NEGOTIABLES.md`
3. `03_SOURCE_ARCHIVE_AUDIT_BASELINE.md`
4. `04_WORKSPACE_BRANCH_GIT_POLICY.md`
5. `05_ENVIRONMENT_SECRETS_DEPENDENCIES.md`
6. `06_PROFILE_B_OBJECTIVE_GATES_VERDICTS.md`
7. `07_MESA_RUNTIME_PROVIDER_PREFLIGHT.md`
8. `08_MESA_DATA_QUALITY_REVIEW_RUNBOOK.md`
9. `09_NATIVE_MESA_DATA_TO_MESA_CONTRACT.md`
10. `10_CORPUS_DESIGN.md`
11. `11_HUMAN_H1_APPROVAL.md`
12. `12_GROUND_TRUTH_FREEZE.md`
13. `13_BENCHMARK_CONFIG_FREEZE.md`
14. `14_EXECUTION_PHASES.md`
15. `15_RETRIEVAL_SCORING.md`
16. `16_GRAPH_PROOF_AND_ABLATION.md`
17. `17_FINAL_ANSWER_GENERATION_AND_GRADING.md`
18. `18_ISOLATION_IDEMPOTENCY_RESTART_PROVENANCE.md`
19. `19_FAILURE_TRIAGE_REPAIR_RESTART.md`
20. `20_RESOURCE_AND_PROVIDER_BUDGETS.md`
21. `21_EVIDENCE_MANIFEST_AND_INTEGRITY.md`
22. `22_LIVE_STATUS_TEMPLATE.md`
23. `23_FINAL_REPORT_TEMPLATE.md`
24. `24_QUICK_COMMAND_DISCOVERY_MAP.md`
25. `25_POST_FIX_PRELAUNCH_CHECKLIST.md`
26. `26_EXPECTED_OUTPUTS_AND_ASSERTIONS.md`
27. `27_FINAL_AGENT_SELF_AUDIT.md`
28. `28_AUTONOMOUS_DECISION_DOCTRINE.md`
29. `MANIFEST.md`

Do not start the benchmark after reading only the master prompt.

## Working directories

The certification repository root is authoritative and must be discovered, never hard-coded:

```bash
CERT_ROOT="$(git rev-parse --show-toplevel)"
```

Expected logical layout:

```text
<CERT_ROOT>/
├── agent-pack/
├── config/
├── datasets/
├── ground-truth/
├── harness/
├── evidence/
├── runs/
├── reports/
└── scripts/
```

MESA and MESA_Data are separate Git repositories under test. Discover their actual paths before use. The VM may commonly place them under `~/mesa-cert/repos/`, but that is a convenience, not a contract.

Secrets must remain outside the certification Git repository. A common protected location is `~/mesa-cert/secrets/nvidia.env`.

For every run use repository-relative certification storage:

```text
<CERT_ROOT>/runs/<RUN_ID>/
<CERT_ROOT>/evidence/<RUN_ID>/
<CERT_ROOT>/datasets/runtime/<RUN_ID>/
<CERT_ROOT>/reports/generated/<RUN_ID>/
```

Runtime/generated content is intentionally not product source code. Do not silently relocate it; record any necessary alternate path in the run manifest.

## Dedicated branch

Use the same branch name in all three repositories (certification repository, MESA, and MESA_Data):

```text
cert/profile-b-e2e
```

Never commit Profile B fixes directly to `main`. See `04_WORKSPACE_BRANCH_GIT_POLICY.md`.

## One human gate, by design

Automation may collect, parse, validate, build a release, create benchmark ground truth, publish, ingest, search, score, repair code, and restart runs. The human is required only for the **hash-bound H1 final corpus/release review and permission to deliver the approved release to MESA**.

The agent must never forge H1 or reinterpret silence as approval.

## Non-pass outcomes are legitimate

The agent must prefer a truthful failure over a false pass. Allowed final verdicts are defined in `06_PROFILE_B_OBJECTIVE_GATES_VERDICTS.md`. In particular, a diagnostic bridge that bypasses MESA_Data's native publisher can help debug but **cannot produce a Profile B pass**.

## Critical rule after any code change

Any product, harness, dependency, Compose, benchmark logic, or scoring code change after a run begins invalidates the current certification run. Preserve its evidence, mark it invalidated, create a new `RUN_ID`, use clean MESA storage and a clean MESA_Data run root, and start again from Phase 0.

Do not delete failed evidence to make the final directory look clean.


<!-- V3.1_FRESH_MAIN_LOCK -->
## Fresh-main lock before autonomous work

Before creating or reusing `cert/profile-b-e2e`, synchronize **all three** repositories with their remote `main` using the clean-baseline procedure in `04_WORKSPACE_BRANCH_GIT_POLICY.md`. Record the resulting `origin/main` SHAs.

Once a `RUN_ID` is created, do **not** pull, merge, rebase, or otherwise absorb newer remote commits into that active run. A desired upstream update requires preserving/invalidation of the current run, resynchronizing from `main`, creating a new coherent baseline, and starting with a new `RUN_ID`.

## Phase -1 workspace hygiene

Before Phase 0, the agent MUST execute
`29_WORKSPACE_HYGIENE_AND_ISOLATION.md`.

The agent must inventory historical VM state, isolate a fresh RUN_ID runtime,
prove that old MESA/MESA_Data state is not reused, inventory Docker state, and
write `runs/<RUN_ID>/workspace-baseline.json`.

Unknown or user-owned files must not be deleted.

## VM bootstrap comes first

On a fresh/restored VM, the first mandatory document is:

`30_VM_BOOTSTRAP_AND_CANONICAL_WORKSPACE_LAYOUT.md`

It establishes the canonical `$HOME/mesa-cert` layout, authoritative repository
paths, safe normalization behavior, runtime namespace rules and bootstrap
evidence.

Then execute `29_WORKSPACE_HYGIENE_AND_ISOLATION.md`, followed by Phase 0.

If an existing workspace does not match the canonical layout, do not destroy
it. Prefer a fresh canonical checkout/runtime and preserve historical/user data.
