# 29 — Workspace Hygiene and Isolation

## Purpose

Profile B must never inherit state from earlier manual experiments, failed runs,
old datasets, stale databases, old Docker volumes, temporary scripts, or other
uncertified runtime artifacts.

This phase is **Phase -1** and runs before Phase 0.

The goal is **isolation, not destructive cleanup**.

The agent MUST prefer creating a new clean runtime namespace over deleting
unknown historical files.

---

## Core rule

A Profile B run is valid only when the agent can prove that:

- MESA runtime storage for the new RUN_ID is clean,
- MESA_Data runtime data root for the new RUN_ID is clean,
- old certification runtime state is not reused,
- stale Docker state cannot contaminate the run,
- secrets are preserved and never printed,
- unknown or user-owned files are not deleted,
- the repositories are updated from their intended upstream only after the
  workspace inventory/isolation step is complete,
- every cleanup/isolation decision is recorded.

---

## Phase -1 workflow

### 1. Discover the actual workspace

Do not assume hard-coded locations.

Discover:

- certification repository,
- MESA repository,
- MESA_Data repository,
- existing `~/mesa-cert` or equivalent certification workspace,
- runtime directories,
- result directories,
- previous dataset roots,
- previous evidence directories,
- previous logs,
- SQLite files,
- LanceDB directories,
- Kùzu directories,
- caches,
- temporary scripts,
- Docker containers,
- Docker volumes,
- Docker networks,
- secret locations.

Record paths, metadata, size and ownership when safe.

Never print secret values.

### 2. Inventory previous state

Classify discovered artifacts as one of:

- `PRODUCT_REPOSITORY`
- `CERTIFICATION_REPOSITORY`
- `SECRET`
- `PRIOR_CERT_RUN`
- `PRIOR_MANUAL_TEST`
- `RUNTIME_STORAGE`
- `CACHE`
- `LOG`
- `UNKNOWN_USER_DATA`

The agent MUST NOT classify an artifact as disposable merely because its name
contains `test`, `tmp`, `old`, `mesa`, or `cert`.

### 3. Do not perform broad destructive cleanup

Forbidden without explicit, verified ownership and necessity:

```bash
rm -rf ~/mesa-cert/*
git clean -fdx
git reset --hard
docker system prune -a
docker volume prune
docker network prune
```

Also forbidden:

- deleting unknown files to free space,
- deleting old evidence,
- deleting failed certification runs,
- deleting secrets,
- deleting arbitrary Docker volumes,
- wiping a repository with uncommitted user work.

### 4. Prefer a fresh RUN_ID namespace

Generate a new RUN_ID and isolate all mutable runtime state under it.

Preferred logical structure:

```text
<cert-workspace>/
├── repos/
│   ├── MESA/
│   ├── MESA_Data/
│   └── MESA_E2E_Certification/
├── runtime/
│   └── <RUN_ID>/
│       ├── mesa/
│       │   ├── sqlite/
│       │   ├── lancedb/
│       │   └── kuzu/
│       ├── mesa-data/
│       └── temp/
├── evidence/
│   └── <RUN_ID>/
├── archive/
└── secrets/
```

The physical layout may differ if the current products require another layout.
If it differs, discover the real configuration and record the mapping.

### 5. Isolate MESA

The new run MUST use fresh MESA mutable state.

At minimum identify and isolate:

- canonical SQLite state,
- vector/LanceDB state,
- Kùzu graph state,
- queues or worker state,
- local cache that affects correctness,
- runtime logs.

The agent MUST prove that the new run did not start from records created by a
previous run.

### 6. Isolate MESA_Data

The new run MUST use a fresh MESA_Data runtime data root or an explicitly
immutable, hash-addressed input snapshot allowed by the certification plan.

Do not silently reuse:

- a previous mutable review database,
- previous pending approvals,
- previous release state,
- previous delivery ledger,
- previous temporary canonical output.

Approved immutable source snapshots may be reused only when their hashes and
provenance are recorded and the certification contract explicitly permits it.

### 7. Isolate Docker state

Before starting services, inventory:

```bash
docker ps -a
docker volume ls
docker network ls
```

Do not delete unrelated resources.

Certification-created Docker resources SHOULD use a RUN_ID-scoped project/name
where the product tooling permits it, for example:

```text
mesa-profile-b-<RUN_ID>-...
```

The agent MUST determine which containers, volumes and networks belong to the
current run before removing or recreating them.

If a stale certification-owned resource conflicts with the new run:

1. prove ownership,
2. preserve relevant evidence,
3. remove/recreate only the conflicting certification-owned resource,
4. record the action in the decision log.

### 8. Handle historical artifacts safely

If old certification/manual artifacts are found:

- leave them in place when they cannot contaminate the new run, or
- move clearly certification-owned artifacts to a quarantine/archive location
  when necessary and safe.

Do not move or delete `UNKNOWN_USER_DATA`.

If disk pressure makes cleanup necessary and safe ownership cannot be proven,
stop with `PROFILE_B_BLOCKED_PRECONDITION` rather than guessing.

### 9. Secrets

Secrets may be discovered by path/name only.

Never:

- print secret contents,
- commit secrets,
- copy secrets into evidence,
- hash and publish secret values,
- include API keys in command logs.

Record only safe facts such as:

```text
secret_file_present=true
secret_value_printed=false
```

### 10. Update source repositories only after isolation baseline

After inventory and isolation are established, update the three repositories
according to the Git policy.

For each repository:

```bash
git status --porcelain=v1
git remote -v
git fetch origin --prune
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git status --porcelain=v1
```

Do not destroy a dirty worktree.

If user work is present and cannot be safely separated, stop with
`PROFILE_B_BLOCKED_PRECONDITION`.

Once the run SHA values are frozen, do not pull new upstream commits into the
same run.

---

## Required Phase -1 evidence

Create:

```text
runs/<RUN_ID>/workspace-baseline.json
```

It MUST include at least:

```json
{
  "run_id": "<RUN_ID>",
  "old_runtime_reused": false,
  "mesa_storage_clean": true,
  "mesa_data_root_clean": true,
  "unknown_files_deleted": false,
  "secrets_printed": false,
  "docker_state_inventoried": true,
  "docker_state_isolated": true,
  "repositories_updated_from_origin_main": true,
  "frozen_repository_shas": {
    "MESA_E2E_Certification": "<sha>",
    "MESA": "<sha>",
    "MESA_Data": "<sha>"
  }
}
```

Also record safe inventories or summaries for:

- historical runtime state,
- relevant disk usage,
- Docker resources,
- selected runtime paths,
- quarantine/archive actions,
- repository SHAs.

Do not place secret values in any evidence file.

---

## Unexpected situations

This phase is governed by `28_AUTONOMOUS_DECISION_DOCTRINE.md`.

When an unlisted situation occurs, the agent SHOULD choose the option that is:

1. safest,
2. least destructive,
3. reversible,
4. smallest in scope,
5. consistent with the current product architecture,
6. least likely to change benchmark meaning,
7. best supported by runtime/source evidence.

Record material decisions in:

```text
runs/<RUN_ID>/decision_log.jsonl
```

If a decision would:

- destroy uncertain user data,
- weaken a hard gate,
- change benchmark semantics,
- expose a secret,
- bypass H1,
- replace native integration with a bridge,
- or make an irreversible security-sensitive change,

the agent MUST stop rather than infer permission.

---

## Phase -1 PASS conditions

Phase -1 PASS requires all of the following:

- workspace inventory completed,
- no unknown user data deleted,
- no secrets printed,
- repositories identified,
- repository worktrees safe,
- fresh RUN_ID created,
- fresh MESA mutable storage selected,
- fresh MESA_Data mutable root selected,
- Docker state inventoried and isolated,
- historical state cannot contaminate the run,
- current upstream `main` fetched/pulled safely,
- exact repository SHAs recorded,
- `workspace-baseline.json` written,
- material autonomous decisions logged.

If any condition cannot be established, do not start Phase 0.

## Relationship to VM bootstrap

`30_VM_BOOTSTRAP_AND_CANONICAL_WORKSPACE_LAYOUT.md` executes before this
document.

Document 30 establishes the canonical workspace and safely normalizes any
existing non-canonical layout.

This document then inventories historical state and proves that none of that
state contaminates the new RUN_ID.

Do not reverse these responsibilities.
