> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 21 — EVIDENCE, MANIFEST AND INTEGRITY

## Run directory

Use:

```text
<CERT_ROOT>/evidence/<RUN_ID>/
```

Recommended immutable structure:

```text
00_manifest/
01_baseline/
02_provider/
03_runtime/
04_data/
05_h1/
06_ground_truth/
07_config_freeze/
08_native_publish/
09_restart_idempotency/
10_isolation/
11_retrieval/
12_graph/
13_answers/
14_resources/
15_failures/
16_ci/
17_final/
```

## RUN_ID

Use UTC and a short baseline fingerprint, e.g.:

```text
B-20260830T203000Z-fde363-cd5407
```

Do not reuse an invalidated RUN_ID.

## Evidence handling

- Raw responses/logs are append-only once a phase closes.
- Redact secrets at capture time; do not store then “clean up later.”
- Preserve HTTP status, bounded response body, UTC, latency and request shape with secrets removed.
- Preserve exact GT/config/source/release hashes.
- Failure evidence remains after repairs.

## Manifest

`run_manifest.json` should include:

```text
run_id
created_utc
status
Certification repo SHA/version/branch
MESA SHA/version/branch
MESA_Data SHA/version/branch
OS/Python/uv/Docker/Compose
container image digest
provider labels/endpoints/SDK version/probe times
corpus/release/GT/config hashes
H1 approval hash
phase statuses
invalidated_by (if applicable)
next_run_id (if applicable)
```

## Final hash design — avoid self-hash paradox

Do **not** write the final report's SHA-256 inside the final report itself. That would change the file being hashed.

Correct design:

```text
17_final/final-report.md
17_final/SHA256SUMS.txt
```

`SHA256SUMS.txt` contains hashes of the final report and all selected immutable evidence files/directories via a deterministic file list. The final report may state that integrity is defined by the sibling checksum file, but must not embed its own checksum value.

For this documentation pack, `SHA256SUMS.txt` similarly hashes the Markdown files; it does not hash itself.

## Integrity verification

At finalization:

1. generate sorted file list excluding transient sockets/DB WAL files and `SHA256SUMS.txt` itself;
2. SHA-256 every included file;
3. write sorted checksum file;
4. run `sha256sum -c SHA256SUMS.txt` from the correct root;
5. save verification output;
6. only then assign final verdict.


<!-- V3.1_DECISION_AND_PROMOTION -->
## Autonomous decision journal

Every material action not explicitly prescribed by this pack must be appended to:

```text
<CERT_ROOT>/evidence/<RUN_ID>/00_manifest/decision_log.jsonl
```

Each record contains at minimum `decision_id`, `run_id`, `phase`, `utc`, `situation`, `options_considered`, `selected_option`, `reason`, `evidence_paths`, `impact_on_test`, `changes_hard_gate`, `reversible`, and `requires_human_authorization`. The full decision doctrine is `28_AUTONOMOUS_DECISION_DOCTRINE.md`.

## Final evidence promotion to tracked Git history

Large raw run evidence remains in ignored `evidence/<RUN_ID>/` and `runs/<RUN_ID>/`. After a valid final verdict, create a **small sanitized immutable certification release bundle** under:

```text
<CERT_ROOT>/reports/releases/<RUN_ID>/
```

At minimum promote/copy generated summaries (without secrets or bulky raw payloads):

```text
final-report.md
run_manifest.json
gate-results.json
retrieval-summary.json
answer-summary.json
graph-summary.json
resource-provider-summary.json
frozen-identities.json
identity-map-summary.json
decision-summary.json
repair-summary.json
evidence-index.json
SHA256SUMS.txt
```

Rules:

- every promoted item must identify the originating evidence path/hash and final RUN_ID;
- do not claim promoted summaries are the raw source evidence;
- verify checksums after promotion;
- `reports/releases/<RUN_ID>/` is intended to be Git-tracked so the certification verdict remains auditable if the VM is lost;
- secrets, full raw legal corpora, provider payload dumps, databases and bulky runtime artifacts must not be promoted;
- the report still must not contain its own SHA.

## Workspace baseline evidence

Every run MUST contain:

```text
runs/<RUN_ID>/workspace-baseline.json
```

The final evidence index must reference this file and its SHA-256.

The workspace baseline proves that the run did not inherit mutable state from
older manual tests or certification runs.

## Bootstrap layout evidence

Every final run evidence index must reference:

```text
runs/<RUN_ID>/bootstrap-layout.json
runs/<RUN_ID>/workspace-baseline.json
```

`bootstrap-layout.json` records the canonical filesystem/repository/runtime
mapping.

`workspace-baseline.json` records that historical state cannot contaminate the
run.

Both must be associated with the final RUN_ID and included by SHA-256 in the
evidence index.

## Benchmark integrity artifacts

The evidence index must include SHA-256 references for:

```text
contract-freeze.json
determinism-manifest.json
health-pre-test.json
health-post-test.json
scorer-canary-results.json
```

Finalization must complete before teardown.

Do not modify sealed/hash-listed artifacts silently.

## Harness and GT verification evidence

The evidence index must include hashes/references for:

```text
harness-self-test.json
harness-readiness.json
identity-map-validation.json
oracle-leakage-audit.json
scoring-normalization.json
no-answer-audit.jsonl
GT semantic-validation output
```

Executable harness/scorer source hashes are part of the official contract
freeze.

## Resource guard evidence

Include/checksum:

```text
resource-guard-config.json
resource-telemetry.jsonl
resource-pressure-events.jsonl
```

The compact release bundle must contain a resource/OOM summary including peak
memory, minimum MemAvailable, peak swap, OOM counters and required-container
restart counts.
