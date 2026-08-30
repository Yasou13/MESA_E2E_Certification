> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 14 — END-TO-END EXECUTION PHASES

The agent maintains `status.md` from the template and transitions phases explicitly.

## Phase 0 — Baseline

- read full pack;
- discover repositories/current code;
- clean/fetch main and create/verify cert branches;
- record SHAs/environment;
- run current repo test discovery and relevant baseline tests;
- compare live code with `03_SOURCE_ARCHIVE_AUDIT_BASELINE.md`;
- repair confirmed pre-benchmark blockers; if repaired, commit and create a fresh RUN_ID before continuing.

Exit: clean branch heads, baseline local tests pass, no known P0 contract defect left unresolved.

## Phase 1 — Provider + production runtime preflight

- host MESA Nemotron probe;
- host GPT-OSS adapter + structured + real extraction probe;
- inspect/fix Compose variable parity;
- build production image;
- verify provider identities/config inside running container without leaking secrets;
- authenticated `/health`/capability;
- isolated technical canary ingestion/search/restart.

Exit: B1–B3 ready.

## Phase 2 — MESA_Data data factory

- clean run data root;
- initialize/migrate/doctor/audit;
- official-source collection to candidate pool;
- pipeline canonicalization;
- encoding/mojibake checks;
- parsing coverage/quality checks;
- deterministic 50–60+ selected corpus;
- selected-version hashes and review evidence;
- classify already-approved vs manual-review-required selected versions.

Exit: exact selected corpus candidate ready for final human checkpoint.

## Phase 3 — H1 + immutable release

- build hash-bound H1A review bundle;
- STOP for explicit human selected-version decisions;
- apply only explicitly approved review actions; deterministic replacement for rejected selected versions, with replacement shown within the same checkpoint;
- build and verify immutable release only after all selected versions are eligible;
- freeze deterministic chunk plan;
- show exact release/chunk hashes;
- require explicit H1B full-delivery confirmation;
- record both literal decisions and hashes.

No full corpus publish before H1B.

## Phase 4 — Ground truth + config DEV/freeze

- deterministically partition DEV/TEST evidence;
- build source-only 12 DEV + 80 TEST GT;
- validate and hash GT;
- run DEV configuration check only;
- freeze retrieval/extraction/answer config; hash it.

No TEST calls yet.

## Phase 5 — Native publisher compatibility canary

Use native MESA_Data publisher against real MESA in a dedicated small scope. Prove commit, search provenance and idempotent retry. If native contract fails, repair product code, commit, invalidate run, restart from Phase 0. A bridge may diagnose but cannot advance this gate.

## Phase 6 — Full native release delivery

- provision exact authorized target scope;
- native publish frozen H1-approved release;
- poll all mutations;
- reconcile MESA_Data ledger vs MESA state;
- require zero unexplained failed/rejected items;
- preserve mapping and commit evidence;
- build/validate `identity_map.jsonl` from native publisher/commit metadata only;
- hash/freeze the identity map before any TEST retrieval.

## Phase 7 — Persistence/idempotency/isolation

- restart MESA services;
- verify committed corpus remains searchable;
- republish/retry exact same release and prove no duplicate logical ingestion;
- run tenant/principal negative tests across search/context/catalog visibility.

## Phase 8 — Frozen retrieval TEST

- run all 80 TEST queries once under frozen config;
- save raw response per query before scoring;
- infrastructure errors invalidate the run, not query score;
- score Recall@1, Recall@5, MRR, REL complete-evidence@5 and provenance integrity.

## Phase 9 — Graph proof

- analyze graph-origin public provenance on predesignated REL queries;
- run controlled read-only graph ON/OFF shadow ablation against the exact same data/config/query set;
- score rank/evidence differences.

Do not modify product data or TEST config for ablation.

## Phase 10 — Final answers

- construct context only from frozen top-5 MESA retrieval results;
- call frozen GPT-OSS answer path;
- save raw answers;
- deterministic grading against required facts/evidence IDs/forbidden claims;
- no-answer abstention grading.

## Phase 11 — Resource/CI/integrity finalization

- resource and provider-call summary;
- check Docker/OOM logs/disk growth;
- run final repo local CI-equivalent;
- push final cert branches if authorized;
- verify GitHub Actions green for exact SHAs;
- verify all evidence hashes;
- generate final report and external `SHA256SUMS.txt`.

## Phase 12 — Verdict

Apply hard gates mechanically. Do not average failures away. Emit exactly one allowed verdict plus gate table and limitations.


## Phase -1 — Workspace hygiene and isolation

This phase runs before Phase 0.

Follow `29_WORKSPACE_HYGIENE_AND_ISOLATION.md`.

Required outcome:

- historical state inventoried,
- fresh RUN_ID namespace selected,
- clean MESA mutable storage,
- clean MESA_Data mutable data root,
- Docker state isolated,
- no unknown user data deleted,
- repositories safely updated from `origin/main`,
- exact repository SHAs frozen,
- `runs/<RUN_ID>/workspace-baseline.json` recorded.

If Phase -1 does not PASS, Phase 0 MUST NOT start.

## Bootstrap — before Phase -1

On VM start/restore, execute
`30_VM_BOOTSTRAP_AND_CANONICAL_WORKSPACE_LAYOUT.md`.

Required result:

- canonical `$HOME/mesa-cert` root,
- authoritative canonical repository paths,
- safe normalization of any pre-existing non-canonical layout,
- runtime/evidence/archive/cache/secrets separation,
- tool/dependency inventory,
- ability to create RUN_ID-scoped mutable storage.

Then execute Phase -1 workspace hygiene and isolation.

Bootstrap is not optional on a fresh/restored VM.
