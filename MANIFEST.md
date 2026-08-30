# Certification Repository Manifest

## Identity

- Repository: `MESA_E2E_Certification`
- Certification: **MESA Profile B — Legal End-to-End Integration & Retrieval Certification**
- Test ID: `MESA-PROFILE-B-LEGAL-E2E`
- Agent contract: `agent-pack/00_START_HERE.md` → numbered sequence → `agent-pack/MANIFEST.md`

## Authority

The certification repository defines testing policy and evidence requirements. It does not override the live product contract. Current MESA/MESA_Data source and observed runtime behavior must always be re-discovered and recorded.

## Directory ownership

| Directory | Purpose | Runtime mutability | Expected Git behavior |
|---|---|---:|---|
| `agent-pack/` | authoritative agent instructions | low | tracked |
| `config/` | config contract + frozen benchmark config | controlled | contract tracked; runtime secrets forbidden |
| `datasets/` | corpus specs/manifests | controlled | manifests tracked; bulk runtime data may be ignored |
| `ground-truth/` | independent DEV/TEST truth | freeze-controlled | frozen truth tracked when finalized |
| `harness/` | deterministic runners/scorers | controlled | tracked and tested |
| `evidence/` | raw immutable run evidence | high | normally ignored except documentation/placeholders |
| `runs/` | run state and invalidation metadata | high | normally ignored/generated |
| `reports/` | final/intermediate reporting | medium | templates tracked; generated reports policy-dependent |
| `scripts/` | operational/reproducibility scripts | controlled | tracked and tested |

## Three-repository model

Certification operates across:

1. this certification repository;
2. MESA;
3. MESA_Data.

All three use `cert/profile-b-e2e` during autonomous work. Exact commit SHAs for all three must be recorded for every coherent run.

## Required read order

The canonical numbered read order is defined in `agent-pack/00_START_HERE.md`. Files are intentionally numbered so the agent does not jump from `03` to `06` or otherwise skip dependencies.

## Generated artifacts

The final run must preserve at minimum:

- baseline/runtime manifests;
- provider preflight evidence;
- MESA_Data quality/release evidence;
- H1 approval records;
- frozen GT/config hashes;
- native publisher evidence;
- restart/idempotency/isolation evidence;
- raw retrieval results and deterministic scoring;
- graph provenance and ablation evidence;
- answer outputs and deterministic grading;
- resource/provider-call accounting;
- CI evidence;
- final report;
- external checksum manifest.

## No self-hash

A report must never contain its own SHA-256. Hash the completed report from a sibling checksum file.


<!-- V3.1_REPOSITORY_EDITION -->
## v3.1 repository-edition guarantees

- startup synchronizes and records all three repositories before certification branches/run creation;
- unspecified cases follow `agent-pack/28_AUTONOMOUS_DECISION_DOCTRINE.md` and are logged;
- source acquisition expands deterministically without MESA-result leakage;
- qrels are source-ID based and MESA provenance is reconciled through a frozen native identity map;
- H1 reuse across restarted runs is allowed only as a hash-bound referenced external authorization artifact;
- ambiguous answer cases cannot trigger a hidden second human gate and count non-PASS unless deterministically resolved by pre-frozen rules;
- a sanitized final audit bundle is promoted to Git-tracked `reports/releases/<RUN_ID>/`.

## Workspace hygiene

Profile B begins with Phase -1 workspace hygiene and isolation.

The certification run must not inherit mutable state from previous manual
tests, old MESA storage, old MESA_Data roots or stale Docker resources.
See `agent-pack/29_WORKSPACE_HYGIENE_AND_ISOLATION.md`.

## VM bootstrap and canonical workspace

Fresh/restored VM execution begins with:

`agent-pack/30_VM_BOOTSTRAP_AND_CANONICAL_WORKSPACE_LAYOUT.md`

The canonical Profile B workspace is `$HOME/mesa-cert`.

Existing non-canonical MESA/MESA_Data/certification checkouts are discovered
and normalized safely without destroying unknown user data.

## Benchmark integrity and finalization

Official TEST execution is protected by:

`agent-pack/31_BENCHMARK_INTEGRITY_FREEZE_DETERMINISM_AND_FINALIZATION.md`

This prevents ground-truth leakage, post-result methodology changes, scorer
drift and non-reproducible PASS results.

## Canonical MESA runtime lock

Official Profile B MESA runtime semantics are fixed by:

`agent-pack/32_PROFILE_B_CANONICAL_MESA_RUNTIME_LOCK.md`

This prevents accidental Mode 2 fallback or provider/model drift.

## Executable harness and semantic ground truth

Profile B requires the executable harness and semantic ground-truth validation
contract in:

`agent-pack/33_CERTIFICATION_HARNESS_AND_GROUND_TRUTH_VERIFICATION_CONTRACT.md`

Official TEST is blocked until Phase H0 proves the harness, qrels, normalization
and oracle barrier are correct.
