> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on dedicated certification branches.  
> Authority rule: live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 04 — WORKSPACE, BRANCH AND GIT POLICY

## Repositories

This program operates on three separate Git repositories:

1. **Certification repository** — the repository containing this `agent-pack/` directory.
2. **MESA** — product repository under test.
3. **MESA_Data** — product/data-factory repository under test.

Discover all three roots. Never edit extracted ZIP snapshots as the live repositories.

The certification root is:

```bash
CERT_ROOT="$(git rev-parse --show-toplevel)"
```

Record absolute paths to MESA and MESA_Data in the run manifest after discovery. Do not require one fixed filesystem layout.

## Clean baseline procedure

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

If unexplained changes exist, stop with `BLOCKED_DIRTY_WORKTREE`. Never stash, discard, reset, clean, or overwrite user work without explicit authorization.

## Certification branch

Use the same branch name in all three repositories:

```text
cert/profile-b-e2e
```

Create it from current `origin/main` only after the baseline is clean:

```bash
git switch -c cert/profile-b-e2e origin/main
```

If it already exists, verify clean worktree, purpose, ancestry, remote/local divergence, and all existing commits. If a same-named unrelated or unsafe branch exists, stop as `BLOCKED_BRANCH_COLLISION`; never force-reset it.

## Why the certification repo also gets a branch

Antigravity may need to add or correct:

- deterministic harness code;
- scoring scripts;
- config templates;
- benchmark manifests;
- generated frozen GT/config artifacts intended for source control;
- documentation corrections discovered before the final coherent run.

Those changes belong on `cert/profile-b-e2e`, not `main`.

## Baseline lock

At each run start record:

```text
CERT_REPO_BASELINE_SHA
MESA_BASELINE_SHA
MESA_DATA_BASELINE_SHA
CERT_REPO_CURRENT_SHA
MESA_CURRENT_SHA
MESA_DATA_CURRENT_SHA
branch names
remote URLs without embedded credentials
dirty status
```

The executable certification logic and both product SHAs are immutable during a coherent final run. Runtime evidence files may be created only in designated ignored/generated locations.

If tracked harness/scorer/config-generation logic changes after a run starts, invalidate the run exactly like a product code change.

## Commit policy

Use one logically complete, green commit per fix. Keep every committed state understandable and testable.

Recommended messages:

```text
fix(profile-b): wire external provider settings into v4 runtime
fix(publisher): align native delivery with MESA v4 ingestion contract
test(publisher): cover live v4 payload mapping
fix(cert): correct deterministic retrieval scorer
chore(cert): freeze profile-b benchmark config
```

Rules:

- no unrelated formatting or refactoring;
- no generated runtime evidence committed to MESA/MESA_Data;
- no secrets anywhere in Git;
- no threshold, qrel, expected-answer, or TEST-query edits to hide a failure;
- inspect `git diff --check`, `git diff --stat`, and full diff before commit;
- run focused tests and relevant local CI-equivalent before commit;
- record paired SHAs for every cross-repo repair.

## Push policy

The agent may push only `cert/profile-b-e2e`. Never push `main`, force-push, rewrite public history, merge to main, or open/merge a PR unless the user explicitly requests it.

For MESA and MESA_Data, if authenticated GitHub access exists, verify GitHub Actions for the exact final branch SHAs. If required remote CI cannot be observed because auth/service access is unavailable, use a blocked verdict rather than inventing success.

For the certification repository, run any configured CI if present; absence of a workflow is not by itself a product failure, but local harness self-tests are mandatory.

## Code-change invalidation rule

Any change to MESA, MESA_Data, executable certification harness, scorer, GT-generation logic, benchmark config, Compose/dependency state, or hard-gate logic after a run begins causes:

```text
current run -> INVALIDATED_CODE_CHANGE
preserve old evidence
commit validated fix
new RUN_ID
new clean MESA storage
new clean MESA_Data run root
Phase 0 restart
```

Never copy PASS evidence from an invalidated run into the new run as if it were newly produced.

