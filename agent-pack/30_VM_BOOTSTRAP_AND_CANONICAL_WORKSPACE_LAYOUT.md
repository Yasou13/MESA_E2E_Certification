# 30 — VM Bootstrap and Canonical Workspace Layout

## Purpose

This document defines the canonical filesystem and bootstrap behavior for a
fresh or restored VM snapshot before Profile B certification begins.

It runs **before Phase -1**.

The bootstrap must be able to handle both:

1. a fresh VM where the canonical workspace does not yet exist, and
2. a VM where MESA-related files/repositories already exist in non-canonical
   locations.

The goal is to normalize the certification environment without destroying
unknown user data.

---

# 1. Canonical root

The canonical certification workspace is:

```text
$HOME/mesa-cert
```

The agent MUST use this as the authoritative Profile B workspace unless the
host environment makes it impossible.

If a different root is required, the agent must:

- explain why,
- record the alternative root in `decision_log.jsonl`,
- preserve the same logical layout,
- ensure all later evidence references the actual root.

Do not silently invent multiple certification roots.

---

# 2. Canonical filesystem layout

The desired logical layout is:

```text
$HOME/mesa-cert/
├── repos/
│   ├── MESA/
│   ├── MESA_Data/
│   └── MESA_E2E_Certification/
│
├── runtime/
│   ├── current -> <RUN_ID>/
│   └── <RUN_ID>/
│       ├── mesa/
│       │   ├── sqlite/
│       │   ├── lancedb/
│       │   ├── kuzu/
│       │   ├── logs/
│       │   └── temp/
│       │
│       ├── mesa-data/
│       │   ├── data/
│       │   ├── logs/
│       │   └── temp/
│       │
│       └── shared-temp/
│
├── evidence/
│   └── <RUN_ID>/
│
├── archive/
│   ├── failed-runs/
│   └── pre-profile-b/
│
├── cache/
│
└── secrets/
    └── nvidia.env
```

The physical subdirectories used by MESA or MESA_Data may differ if current
product configuration requires it. In that case:

- preserve the canonical top-level separation,
- map product-specific paths explicitly,
- record the mapping in the run baseline,
- never place mutable databases inside the Git repositories.

---

# 3. Canonical repository paths

The authoritative product checkouts for Profile B are:

```text
$HOME/mesa-cert/repos/MESA
$HOME/mesa-cert/repos/MESA_Data
$HOME/mesa-cert/repos/MESA_E2E_Certification
```

Expected upstream repositories are:

```text
https://github.com/Yasou13/MESA.git
https://github.com/Yasou13/MESA_Data.git
https://github.com/Yasou13/MESA_E2E_Certification.git
```

Before trusting a checkout, verify its actual Git remote.

The live Git remote is evidence; a folder name is not.

Do not mistake archives such as:

```text
MESA-main/
MESA-main (14)/
MESA_Data-main/
Downloads/MESA/
Desktop/MESA-test/
```

for authoritative Git repositories.

---

# 4. Bootstrap ordering

The VM bootstrap order is:

```text
VM boot / snapshot restore
        ↓
host inventory
        ↓
canonical root discovery/creation
        ↓
existing MESA-related workspace discovery
        ↓
safe normalization of repositories
        ↓
canonical runtime/evidence/archive/cache/secrets directories
        ↓
dependency/tool availability check
        ↓
secret presence check without printing values
        ↓
Phase -1 workspace hygiene and isolation
        ↓
safe origin/main update
        ↓
RUN_ID creation and runtime binding
        ↓
Phase 0
```

`30` defines where the system lives.

`29_WORKSPACE_HYGIENE_AND_ISOLATION.md` defines how historical state is
inventoried and prevented from contaminating the run.

---

# 5. Existing workspace normalization

The agent MUST be capable of finding an existing setup that does not match the
canonical layout and normalizing the certification environment safely.

## 5.1 Discovery

Search likely locations without assuming ownership:

```text
$HOME/mesa-cert
$HOME/Desktop
$HOME/Documents
$HOME/Downloads
$HOME
```

Look for:

- Git repositories whose remotes identify MESA, MESA_Data, or the certification repo,
- old `mesa-cert` trees,
- old runtime/results/evidence directories,
- old SQLite/LanceDB/Kùzu state,
- MESA_Data data roots,
- secret files by path/name only,
- Docker resources.

Do not perform an unbounded recursive scan of the entire filesystem unless
necessary.

## 5.2 If the canonical repository path does not exist

If a valid repository exists elsewhere:

### Preferred behavior

Create a **fresh canonical checkout from its verified `origin`** at the canonical
path and leave the old checkout untouched.

This is preferred over moving the old repository because:

- user work remains safe,
- hidden build/runtime files are not inherited,
- the canonical checkout is reproducible.

After cloning:

- fetch `origin`,
- verify default/upstream branch,
- later update `main` with `--ff-only`,
- record old checkout location as historical state.

### Do not

- delete the old checkout,
- move a dirty checkout automatically,
- copy `.venv`, databases, caches, logs, or runtime state into the canonical repo.

## 5.3 If the canonical repository path already exists

Verify:

1. it is a Git repository,
2. its remote identifies the expected project,
3. its worktree is safe,
4. it is not an extracted ZIP masquerading as a Git checkout.

Then:

### Correct repo + clean worktree
Use it and update it according to Git policy.

### Correct repo + dirty worktree
Do not reset, clean, stash, overwrite, or discard user work automatically.

Prefer creating a fresh canonical replacement only if a separate safe path can
be used without overwriting existing data and the canonical path can be
resolved safely. Otherwise stop with:

```text
PROFILE_B_BLOCKED_PRECONDITION
```

### Wrong repo / unknown directory at canonical path
Do not overwrite it.

Record the conflict and stop with `PROFILE_B_BLOCKED_PRECONDITION` unless the
directory is provably certification-owned and can be safely relocated under
the decision doctrine.

---

# 6. Certification repository relocation case

A common bootstrap case is:

```text
$HOME/Desktop/MESA_E2E_Certification
```

already exists because the user created/cloned it manually.

If it is:

- the correct Git repository,
- clean,
- fully pushed,
- and the canonical path is absent,

the agent SHOULD prefer a fresh clone into:

```text
$HOME/mesa-cert/repos/MESA_E2E_Certification
```

from the verified `origin`.

Leave the Desktop checkout untouched.

The canonical clone becomes the repository used by the certification run.

This prevents Profile B from depending on Desktop-specific paths.

---

# 7. Canonical directory creation

After resolving repository conflicts, ensure these directories exist:

```bash
mkdir -p \
  "$HOME/mesa-cert/repos" \
  "$HOME/mesa-cert/runtime" \
  "$HOME/mesa-cert/evidence" \
  "$HOME/mesa-cert/archive/failed-runs" \
  "$HOME/mesa-cert/archive/pre-profile-b" \
  "$HOME/mesa-cert/cache" \
  "$HOME/mesa-cert/secrets"
```

Do not create mutable runtime DBs until a RUN_ID exists.

---

# 8. Secrets

Preferred NVIDIA secret path:

```text
$HOME/mesa-cert/secrets/nvidia.env
```

If the secret already exists elsewhere:

- do not print it,
- do not commit it,
- do not move/copy it blindly,
- determine whether the current path is safe,
- if normalization is necessary, preserve permissions and never log the value,
- record only the resulting safe path.

Recommended permission:

```bash
chmod 600 "$HOME/mesa-cert/secrets/nvidia.env"
```

Do not fail merely because a secret uses a different safe path if the runtime
can consume it securely. Record the deviation.

---

# 9. RUN_ID runtime creation

After Phase -1 has established a clean baseline, create a unique RUN_ID.

Example format:

```text
RUN-YYYYMMDDTHHMMSSZ-<short-random>
```

For the new run:

```text
$HOME/mesa-cert/runtime/<RUN_ID>/
$HOME/mesa-cert/evidence/<RUN_ID>/
```

Create at least:

```text
runtime/<RUN_ID>/mesa/sqlite/
runtime/<RUN_ID>/mesa/lancedb/
runtime/<RUN_ID>/mesa/kuzu/
runtime/<RUN_ID>/mesa/logs/
runtime/<RUN_ID>/mesa/temp/
runtime/<RUN_ID>/mesa-data/data/
runtime/<RUN_ID>/mesa-data/logs/
runtime/<RUN_ID>/mesa-data/temp/
runtime/<RUN_ID>/shared-temp/
evidence/<RUN_ID>/
```

The `runtime/current` symlink MAY point at the active RUN_ID for operator
convenience:

```bash
ln -sfn "<RUN_ID>" "$HOME/mesa-cert/runtime/current"
```

The symlink is convenience only. Evidence must record the exact RUN_ID.

---

# 10. Bind products to the RUN_ID

Before starting MESA or MESA_Data, discover their current configuration keys.

Then ensure all mutable correctness-relevant state points at the current
RUN_ID.

At minimum:

## MESA

Bind:

- canonical SQL/SQLite storage,
- LanceDB/vector storage,
- Kùzu graph storage,
- runtime logs,
- temporary state,
- any queue/worker state affecting correctness.

## MESA_Data

Bind:

- data root,
- mutable review DB/state,
- release working state,
- delivery ledger,
- logs,
- temporary canonicalization output.

If a product forces a different directory shape, document the actual mapping
in:

```text
runs/<RUN_ID>/workspace-baseline.json
```

Never silently use a default path that may contain state from an older run.

---

# 11. Docker namespace

Where current tooling permits, use a RUN_ID-scoped Compose project name:

```text
COMPOSE_PROJECT_NAME=mesa-profile-b-<RUN_ID>
```

or an equivalent safe normalized form.

The purpose is to keep:

- containers,
- networks,
- named volumes

separate between runs.

Do not rely on container names alone to prove storage isolation.

Record the actual Compose project name and relevant Docker resource IDs/names.

---

# 12. Existing old runtime layout

If an older layout exists, for example:

```text
$HOME/mesa-cert/results/
$HOME/mesa-cert/datasets/profile-b/
$HOME/mesa-cert/storage/
$HOME/mesa-cert/tmp/
```

do not automatically delete it.

Instead:

1. inventory it under Phase -1,
2. determine whether it can contaminate the new run,
3. use new RUN_ID paths that do not reference it,
4. leave it untouched if isolation is sufficient,
5. quarantine only clearly certification-owned artifacts when necessary,
6. record any relocation in `decision_log.jsonl`.

The new canonical layout does not require destructive migration of history.

---

# 13. Tool/dependency bootstrap

Check availability of at least:

```text
git
python
uv
docker
docker compose
curl
sha256sum
```

Use current project documentation/lockfiles to determine exact runtime
dependencies.

Do not globally upgrade unrelated system packages merely because newer
versions exist.

If a required tool is missing:

1. determine the smallest supported installation,
2. install only if permitted and safe,
3. record the installed version,
4. otherwise stop with `PROFILE_B_BLOCKED_PRECONDITION`.

Do not weaken the test because a dependency is inconvenient.

---

# 14. Repository update rule

After canonical checkouts are established and Phase -1 has confirmed safe
worktrees, update all three repositories:

```bash
git fetch origin --prune
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

Record exact SHAs.

Then create/use the certification working branch according to
`04_WORKSPACE_BRANCH_GIT_POLICY.md`.

Once a RUN begins and SHAs are frozen, do not pull new upstream commits into
that same RUN.

---

# 15. Bootstrap evidence

Write:

```text
runs/<RUN_ID>/bootstrap-layout.json
```

It should include at least:

```json
{
  "canonical_root": "/home/<user>/mesa-cert",
  "repositories": {
    "MESA": {
      "path": "/home/<user>/mesa-cert/repos/MESA",
      "origin": "<verified origin>",
      "sha": "<sha>"
    },
    "MESA_Data": {
      "path": "/home/<user>/mesa-cert/repos/MESA_Data",
      "origin": "<verified origin>",
      "sha": "<sha>"
    },
    "MESA_E2E_Certification": {
      "path": "/home/<user>/mesa-cert/repos/MESA_E2E_Certification",
      "origin": "<verified origin>",
      "sha": "<sha>"
    }
  },
  "runtime_root": "/home/<user>/mesa-cert/runtime/<RUN_ID>",
  "evidence_root": "/home/<user>/mesa-cert/evidence/<RUN_ID>",
  "old_noncanonical_checkouts_preserved": true,
  "unknown_user_data_deleted": false,
  "docker_project": "<name-or-null>",
  "secret_path_recorded_without_value": true
}
```

Do not include secrets.

---

# 16. Safe normalization decision hierarchy

When the existing VM layout differs from the canonical layout, choose in this
order:

1. **Reuse canonical clean state** if already correct.
2. **Fresh clone into canonical path** while preserving old checkout.
3. **Create isolated new RUN_ID runtime** instead of moving old runtime.
4. **Leave non-contaminating historical data untouched.**
5. **Quarantine provably certification-owned state** only when necessary.
6. **Stop** if normalization would require guessing about user ownership or
   destroying uncertain data.

This hierarchy overrides convenience.

---

# 17. Autonomous decision logging

Any material deviation or normalization action must be written to:

```text
runs/<RUN_ID>/decision_log.jsonl
```

Examples:

- canonical path occupied,
- existing checkout preserved and fresh clone created,
- alternate secret path retained,
- product-specific storage path differs from preferred layout,
- Docker project naming needed normalization,
- historical certification-owned state quarantined.

Use `28_AUTONOMOUS_DECISION_DOCTRINE.md`.

---

# 18. Bootstrap PASS conditions

Bootstrap PASS requires:

- canonical root resolved,
- all three authoritative repositories resolved,
- repository origins verified,
- no unknown data overwritten,
- canonical non-repository directories created,
- required tools inventoried,
- secret handling path established safely,
- Phase -1 can execute,
- fresh RUN_ID paths can be created,
- product mutable storage can be bound to the RUN_ID,
- Docker namespace can be isolated or an equivalent isolation proven,
- bootstrap evidence is recorded.

If this cannot be proven, do not proceed to Phase -1/Phase 0.

---

# 19. Relationship to other documents

Execution order at VM start is:

```text
30_VM_BOOTSTRAP_AND_CANONICAL_WORKSPACE_LAYOUT.md
        ↓
29_WORKSPACE_HYGIENE_AND_ISOLATION.md
        ↓
Phase 0 and the remaining Profile B execution plan
```

Document `30` establishes the canonical workspace.

Document `29` proves historical state cannot contaminate the run.

Both are mandatory for a fresh or restored VM.

## Supply-chain bootstrap boundary

Bootstrap should prefer project lockfiles and documented tooling.

Do not globally upgrade unrelated dependencies or install arbitrary latest
packages to make certification proceed.

Any necessary new certification dependency must be pinned/locked in the proper
repository and causes refreeze/new RUN if added after contract freeze.
