# 35 — Agent Token and Fresh-VM Execution Efficiency

## Purpose

Profile B is intended to run autonomously on a fresh/restored Ubuntu
certification VM without wasting:

- agent reasoning/context tokens,
- NVIDIA provider tokens/calls,
- shell/tool calls,
- repeated repository scans,
- repeated package installs,
- repeated builds/tests,
- RAM,
- disk I/O,
- wall-clock time.

Efficiency is subordinate to correctness.

The agent MUST NOT skip a required certification gate merely to save tokens or
time.

---

# 1. Fresh/restored VM is a first-class execution mode

The expected user workflow may be:

```text
restore clean Ubuntu snapshot
        ↓
start Antigravity
        ↓
clone/open MESA_E2E_Certification
        ↓
execute Profile B autonomously
```

The agent must support this directly.

Do not assume that `$HOME/mesa-cert` already exists.

On a genuinely fresh/restored VM:

1. inspect the host with bounded commands,
2. establish `$HOME/mesa-cert`,
3. clone/verify the three authoritative repositories,
4. establish secret path without printing secret values,
5. install only genuinely missing required dependencies,
6. create a fresh RUN_ID,
7. create isolated runtime/storage/evidence paths,
8. execute Phase -1 and the remaining certification plan.

Use document 30 as the authoritative workspace/bootstrap contract.

---

# 2. Initial document read vs repeated rereads

At the beginning of an autonomous certification session, the agent MUST read
the numbered agent-pack contracts in the mandatory order from
`00_START_HERE.md`.

That initial full contract read is required.

After the initial read:

- do not repeatedly reread every Markdown document,
- use the current phase to select only relevant contract files,
- use `agent-pack/SHA256SUMS.txt` to detect whether the pack changed,
- if checksums are unchanged, rely on the previously established contract map,
- reread a contract when entering its phase or when its checksum changed,
- always reread any contract directly implicated by a failure before changing
  behavior.

Token efficiency must not cause the agent to forget later-numbered contracts.

---

# 3. Phase-scoped contract map

After the initial full read, use approximately this scope:

```text
Bootstrap:
  30, 34, 35

Phase -1:
  29, 30, 34, 35

Phase 0 / baseline:
  03, 04, 05, 30, 31, 34, 35

Phase H0:
  13, 21, 25, 26, 31, 33, 34, 35

Provider/runtime:
  05, 07, 20, 31, 32, 34, 35

MESA_Data/corpus/H1:
  08, 10, 11, 12, 19, 21, 34, 35

Native publish:
  09, 18, 19, 20, 21, 34, 35

Retrieval/graph:
  13, 15, 16, 18, 20, 31, 33, 34, 35

Final answer:
  13, 17, 20, 31, 32, 33, 34, 35

Finalization:
  21, 23, 25, 26, 27, 31, 34, 35
```

This map is an efficiency aid only.

If another contract is relevant, read it.

---

# 4. Discovery cache keyed by source/config identity

Repeatedly rediscovering unchanged APIs/configuration wastes tokens and time.

Create:

```text
runs/<RUN_ID>/agent-discovery-cache.json
```

Cache only verified non-secret facts such as:

```text
MESA SHA
MESA_Data SHA
certification SHA
Compose file hash
relevant config-file hashes
public API paths
CLI entry points
current env/config key names
provider config mapping
storage paths
test commands
build commands
health commands
native publisher contract mapping
```

Every cached fact must include the identity/hash on which it depends.

Reuse a discovery only when its dependency hashes still match.

Never cache or store secret values.

If source/config identity changed, invalidate only the affected cache entries
and rediscover them.

---

# 5. Agent checkpoint for context recovery

Maintain a compact machine-readable checkpoint:

```text
runs/<RUN_ID>/agent-checkpoint.json
```

Update it at meaningful phase boundaries.

Recommended fields:

```text
run_id
current_phase
phase_status
repository_shas
agent_pack_sha256
contract_freeze_sha
current_blocker
last_completed_gate
next_required_action
important_evidence_refs
effective_runtime_identity
resource_pressure_state
human_gate_state
```

If agent context is compacted/lost/restarted:

```text
read agent-checkpoint.json
        ↓
read run/status/manifest evidence
        ↓
verify SHAs/checksums
        ↓
read only the current/relevant contracts
        ↓
continue
```

Do not rebuild understanding by rereading all logs and repositories from zero
unless integrity cannot otherwise be established.

---

# 6. Source-code inspection strategy

Use narrow-to-wide discovery.

Preferred sequence:

```text
rg/grep/find exact symbol/config/API term
        ↓
inspect matching filenames/line ranges
        ↓
trace direct callers/callees
        ↓
expand only when necessary
```

Avoid as a default:

```text
cat every source file
recursive dump of entire repository
printing entire database
printing complete Docker logs
printing full dependency trees repeatedly
```

Large source files should be inspected by relevant ranges.

A full repository scan is justified only when the question genuinely requires
it.

---

# 7. Large-output discipline

Large command output must normally go to evidence files.

Examples:

```text
pytest full output
Docker logs
provider smoke logs
MESA ingestion logs
MESA_Data pipeline logs
large JSON responses
resource telemetry
```

Then inspect:

- summary,
- exit code,
- failing section,
- bounded tail/head,
- relevant grep matches.

Do not inject megabytes of unchanged logs into agent context.

Preserve raw evidence on disk.

---

# 8. Test escalation ladder

For a reproduced code defect:

```text
minimal reproducer
        ↓
focused regression test
        ↓
focused component/module tests
        ↓
relevant repository CI-equivalent
        ↓
full suite only at required checkpoint
```

Do not run the entire test suite after every tiny edit unless the product's
architecture makes focused verification unsafe.

Do not skip the required final CI-equivalent/full validation.

---

# 9. Avoid repeated provider smoke calls

Real NVIDIA calls cost time/tokens.

Within one RUN, a successful provider smoke result may be reused when all
material identities remain unchanged:

```text
provider endpoint
model identity
provider SDK
MESA source SHA
relevant provider/config hashes
effective runtime mapping
container image/config identity
```

After a simple service restart:

- re-check health/effective runtime identity cheaply,
- do not automatically repeat expensive semantic smoke calls if identity and
  config are unchanged.

Repeat the real provider smoke when:

- provider/model/config identity changes,
- relevant product/provider code changes,
- evidence is missing/corrupt,
- behavior suggests the previous proof no longer applies.

Do not reuse provider proof across a code/config identity that changed.

---

# 10. Provider-token budget

Document 20 remains authoritative for retry/call limits.

Additionally track, when provider metadata exposes it:

```text
prompt/input tokens
completion/output tokens
total tokens
request count
retry count
phase
operation class
```

Create or include in the run's provider budget evidence a per-phase summary.

The agent should investigate before continuing when token/call consumption is
materially above the frozen expectation.

Do not reduce required extraction/answer correctness merely to hit a token
budget.

---

# 11. Extraction efficiency

Official Profile B extraction still follows document 32.

Do not reduce `max_tokens` below the canonical minimum merely to save tokens.

Efficiency measures should instead prefer:

- correct batch sizing established before freeze,
- avoiding duplicate ingestion,
- idempotent retry,
- avoiding repeated extraction of unchanged source chunks,
- avoiding accidental double workers/publishers,
- preventing product+harness retry storms.

If a chunk was already accepted/committed under the same stable idempotency
identity, do not intentionally resubmit it just to recreate evidence.

---

# 12. Official TEST query rule

The frozen official TEST set is not a debugging loop.

For one valid frozen RUN:

```text
each official TEST query
→ execute once
→ persist raw response immediately
→ score only after raw response persistence
```

Do not rerun a poor-performing TEST query to seek a better answer.

If infrastructure/code/config invalidates the RUN:

- preserve the failed run,
- create a new RUN_ID,
- rerun the complete TEST under the new frozen contract.

This rule saves tokens and protects benchmark integrity at the same time.

---

# 13. Final-answer call efficiency

Generate final answers only for the queries required by the frozen Profile B
contract.

Do not ask the answer model to:

- pre-grade its own answer,
- critique itself repeatedly,
- compare against GT,
- regenerate until it matches expected output.

Persist the first valid frozen-contract response.

If an infrastructure error prevents a valid response, apply the existing
bounded failure/retry policy.

---

# 14. Official-source acquisition reuse

Use the raw-source snapshot policy from document 19.

When a restarted run follows a product/config/harness fix that does NOT question
source acquisition correctness:

- reuse the immutable hash-addressed raw source bytes,
- verify every SHA,
- rerun decode/canonical/quality/release logic in the new clean run.

Do not repeatedly redownload unchanged official source bytes merely because the
RUN_ID changed.

If the defect concerns acquisition/download/redirect/MIME/TLS/source selection,
repeat the affected live acquisition checks as required by document 19.

---

# 15. Fresh-VM dependency provisioning

A fresh snapshot may not contain every required system/tool dependency.

The agent may provision missing dependencies autonomously when the action is:

- necessary for Profile B,
- standard for the detected Ubuntu environment,
- bounded,
- non-destructive,
- compatible with project lockfiles/toolchain,
- not dependent on an arbitrary untrusted installer.

Required sequence:

```text
detect OS/package manager
        ↓
inventory existing tools/versions
        ↓
inspect repository lockfiles/package metadata/docs
        ↓
identify genuinely missing prerequisite
        ↓
install minimum required package/tool
        ↓
verify version/function
        ↓
record action
```

Never reinstall an already suitable dependency just because a newer version
exists.

---

# 16. Fresh-VM provisioning safety

Forbidden as the default:

```text
curl <unknown> | sudo bash
pip install --upgrade everything
npm update -g
apt full-upgrade merely for certification
random latest package selection
unbounded dependency upgrades
```

Prefer:

- Ubuntu package manager for required system packages,
- the project's existing installation/bootstrap method,
- `uv`/lockfile-based Python dependency installation where current repos define
  it,
- pinned/locked certification-only dependencies.

If installation requires an irreversible/security-sensitive system change,
follow the autonomous decision doctrine and stop when approval is required.

---

# 17. Provisioning evidence

Write:

```text
runs/<RUN_ID>/provisioning-manifest.json
```

Record:

```text
OS/version
package manager
preexisting required tools
missing required tools
packages/tools installed
requested/installed versions where available
installation reason
verification command/result
repository lockfile hashes
```

Do not include secrets.

A fresh VM with no installation changes should still produce a manifest
showing the inventory.

---

# 18. Bounded filesystem discovery on a fresh snapshot

Document 30 remains authoritative.

Do not start with an unbounded whole-filesystem crawl.

Inspect likely locations such as:

```text
$HOME/mesa-cert
$HOME/Desktop
$HOME/Downloads
expected repo paths
relevant Docker state
known secret location
```

If the VM is demonstrably a fresh/restored clean snapshot and canonical paths
are absent, proceed with fresh canonical setup.

Do not waste time/tokens proving that every unrelated filesystem path lacks an
old MESA checkout.

If evidence suggests historical MESA state exists, execute the stronger
workspace-hygiene discovery required by documents 29/30.

---

# 19. Clone/fetch/pull efficiency

For each repository:

- verify origin,
- verify worktree state,
- fetch only when needed,
- use fast-forward-only update,
- do not reclone a valid clean canonical checkout,
- do not pull repeatedly within the same frozen RUN.

Once SHAs are frozen, no upstream pull is allowed in that RUN.

---

# 20. Build/install efficiency

Avoid repeated environment rebuilds.

If:

```text
repo SHA
lockfile hash
runtime version
virtualenv identity
```

are unchanged and the environment verifies correctly, reuse it within the same
valid run/workspace.

Rebuild/resync when the identity changed or verification fails.

A fresh RUN_ID does not automatically require reinstalling immutable package
dependencies; it requires fresh mutable product state.

---

# 21. Docker efficiency

Do not run repeated full Docker builds when:

```text
Dockerfile hash
Compose hash
build context dependency identity
relevant source SHA
```

are unchanged and the required image identity is already verified.

Do not use stale images when code/config changed.

Do not use aggressive global Docker cleanup to save space/time.

Use the run-scoped Compose project rules from documents 29/30.

---

# 22. Reuse matrix

Safe reuse examples, when hashes/identity prove equivalence:

```text
dependency download/cache
verified virtualenv
verified Docker base/build cache
immutable raw official-source bytes
unchanged API/config discovery cache
initial contract understanding with unchanged SHA256SUMS
```

Must NOT be reused as fresh-run mutable state:

```text
MESA SQLite database
LanceDB mutable store
Kùzu mutable store
queues
MESA_Data mutable DB/review state
delivery ledger
official TEST raw responses from another RUN as current-run results
current-run PASS verdict
```

---

# 23. Avoid duplicate evidence generation

Evidence should be referenced rather than regenerated.

If one artifact already proves the same invariant for the same frozen identity,
later documents/reports should link/reference it.

Do not rerun expensive actions solely to create duplicate screenshots/logs.

Generate a new proof only if:

- the identity changed,
- the required gate demands a distinct runtime transition,
- prior evidence is incomplete,
- a restart/ablation explicitly requires before/after proof.

---

# 24. Failure investigation token discipline

On failure:

1. preserve the exact failure evidence,
2. inspect the smallest relevant log slice,
3. identify the failing component,
4. reproduce minimally,
5. inspect the narrow code path,
6. make the smallest correct change.

Do not react to one failure by repeatedly asking broad questions of the entire
repository.

A broad rescan is justified when the local root-cause hypothesis fails or the
architecture contract is genuinely unclear.

---

# 25. Retry-storm guard

Count effective retries across:

```text
product SDK/client
MESA retry layer
MESA_Data publisher
certification harness
agent-level command retries
```

The agent must reason about the combined retry count.

Do not allow:

```text
3 product retries
× 3 harness retries
× 3 agent retries
```

to become 27 provider calls unintentionally.

Document 20's bounded retry policy remains authoritative.

---

# 26. Agent output verbosity

During execution, live user-facing updates should be compact:

```text
current phase
PASS/FAIL/BLOCKED
important action
current blocker
next step
```

Do not stream every internal command/result to the user unless intervention is
needed.

Full raw evidence belongs in run artifacts.

The final report remains comprehensive as required by the certification
contract.

---

# 27. Efficiency must not weaken evidence

Token/time optimization MUST NOT remove:

- raw TEST responses,
- required provider identity proof,
- H1 human approval,
- GT/source evidence,
- identity-map evidence,
- graph ablation,
- tenant isolation,
- restart/idempotency proof,
- resource/OOM monitoring,
- final checksums/manifests,
- required CI-equivalent tests.

When efficiency and proof conflict, proof wins.

---

# 28. Efficiency evidence

Create:

```text
runs/<RUN_ID>/agent-efficiency-summary.json
```

Recommended fields:

```text
discovery_cache_hits
discovery_cache_misses
full_repo_rescans
provider_requests_by_phase
provider_retries
reported_provider_tokens_by_phase
full_test_suite_runs
focused_test_runs
docker_build_count
dependency_install_actions
official_source_download_count
raw_source_reuse_count
official_test_query_execution_count
official_test_query_reexecution_count
```

For a valid official RUN:

```text
official_test_query_reexecution_count = 0
```

unless the entire prior RUN was invalidated and the count is scoped to the new
RUN.

---

# 29. Fresh-VM readiness PASS

Fresh/restored VM bootstrap is ready to advance only when:

- RAM/disk/resource preconditions pass,
- Antigravity can execute,
- canonical workspace exists,
- all three repos are verified,
- required tools are installed/verified,
- secret location is established without leaking values,
- provisioning manifest exists,
- new RUN_ID exists,
- mutable state is fresh,
- Docker/runtime namespace is isolated,
- agent discovery/checkpoint artifacts can be written.

---

# 30. Final self-check

Before final verdict ask:

- Did I repeatedly reread unchanged docs/repos without reason?
- Did I issue duplicate provider calls without a changed identity?
- Did I repeat official TEST queries in one valid RUN?
- Did I repeatedly rebuild/install unchanged dependencies?
- Did I dump large logs into context instead of inspecting bounded slices?
- Did I exploit efficiency to skip a required gate?
- Did I preserve all raw evidence despite compact reasoning?
- Could context recovery continue from `agent-checkpoint.json` without
  reconstructing the entire run?

Efficiency defects do not automatically make MESA fail, but they must be fixed
when they threaten run validity, cost, resource safety, or autonomous
completion.
