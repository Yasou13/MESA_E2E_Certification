> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 11 — HUMAN H1 APPROVAL

Profile B is autonomous except for one intentional human checkpoint. This reflects the MESA_Data product goal: technical work is automated; a human performs final review/approval before real delivery.

## When H1 occurs

H1 is one final human checkpoint with two tightly-bound stages, because the inspected MESA_Data release builder only includes versions already approved by product state.

H1 starts after:

- source collection;
- decode/canonical pipeline;
- quality/coverage checks;
- deterministic corpus selection;
- selected-version hash/review bundle generation.

### H1A — selected-version review

The human reviews the deterministic sample, every selected warning/audit-sample/manual-review item, and the exact canonical/version hashes. Any selected version that still requires manual product approval is explicitly approved or rejected here. A rejection may be replaced only by the next item from the predeclared deterministic candidate ranking; the replacement must be shown in the same checkpoint before it can join the corpus.

### Between H1A and H1B — agent-only deterministic work

Once selected versions are eligible, the agent builds and verifies the immutable release and chunk plan. No source/canonical content may change.

### H1B — release/delivery confirmation

The agent shows the exact release ID, release manifest SHA and final planned chunk count. The human explicitly confirms delivery of that exact hash. This is still the same final review/approval checkpoint, not a separate development review cycle.

No full legal corpus delivery occurs before H1B.

## Review bundle

The agent must create a human-readable bundle containing:

### H1A summary

- RUN_ID;
- MESA_Data SHA;
- candidate/selected/excluded counts;
- quality PASS/REVIEW/BLOCK counts;
- encoding distribution;
- coverage distribution/min/median;
- selected-versions manifest SHA;
- corpus/review-bundle hashes;
- warnings/blockers list.

H1A occurs **before** release construction, so do not require or invent a release ID, release manifest SHA, or final chunk count at H1A.

### H1B summary extension

After H1A eligibility decisions and deterministic release construction, add:

- exact release ID;
- release manifest SHA;
- planned chunk manifest SHA;
- final planned chunk count.

### Deterministic sample

Show raw↔canonical side-by-side evidence for at least 10 selected documents, chosen before human viewing by a deterministic rule. The sample must include, if present:

- each observed source/content type;
- each observed encoding class, including Windows-1254/cp1254;
- lowest-coverage selected documents;
- at least one long/multi-article document;
- every selected document with a `REVIEW` warning.

All blockers and every warning are included even if that exceeds 10.

### Integrity references

H1A bundle must bind to:

```text
selected_versions_manifest_sha256
corpus_manifest_sha256 (candidate/final membership as applicable)
review_bundle_sha256
MESA_DATA_HEAD_SHA
RUN_ID
```

H1B adds the deterministic post-approval release identity:

```text
release_id
release_manifest_sha256
planned_chunk_manifest_sha256
planned_chunk_count
```

## Approval protocol

The agent displays exact hashes and asks for explicit decisions. Suggested unambiguous forms:

```text
H1A APPROVE CORPUS <RUN_ID> <selected_versions_manifest_sha256-prefix>
H1B APPROVE DELIVERY <RUN_ID> <release_manifest_sha256-prefix>
```

The agent records the human's literal decisions, UTC timestamps and bound hashes in `human_approval.md`. It must not invent either decision.

A rejected document/version is handled only by the deterministic replacement rule above. Rejection of the overall corpus or H1B release/delivery ends the run as `PROFILE_B_ABORTED_HUMAN_GATE` unless the human explicitly asks for a new preparation cycle.

## Approval invalidation

H1 expires if any covered input changes, including:

- MESA_Data code SHA relevant to collection/parse/quality/release/chunking/publisher data mapping;
- selected corpus membership/version;
- canonical bytes;
- release manifest;
- chunk plan;
- release ID/package contents.

A MESA-only downstream bug fix does not alter the approved legal release bytes, but because the certification run restarts, the agent must verify the exact approved release hash is unchanged. It may reuse the same human approval only if the package bytes and all H1-bound hashes are bit-identical and the approval explicitly authorized delivery of that hash; otherwise ask again. Any MESA_Data product fix requires new H1.


<!-- V3.1_H1_REUSE -->
## Hash-bound H1 reuse across a restarted run

H1 approval is an **external authorization artifact bound to immutable hashes**, not ordinary run-generated PASS evidence. A later run may reference a prior H1 approval only when all H1-bound inputs are bit-identical.

Reuse is allowed only when the new run proves all of the following before delivery:

```text
selected_versions_manifest_sha256 identical
corpus_manifest_sha256 identical
review_bundle_sha256 identical
release_id/package contents identical
release_manifest_sha256 identical
planned_chunk_manifest_sha256 identical
canonical bytes/hashes identical
all MESA_Data code affecting collection/parse/quality/release/chunk mapping unchanged
human approval explicitly authorized delivery of that exact release hash
```

A MESA-only downstream fix may therefore reuse H1 if every condition above is proven. The new run manifest must record `h1_origin_run_id`, original approval artifact path/hash, and the revalidation evidence. Do not copy the artifact and pretend it was newly produced by the new run.

Any MESA_Data change that can affect an H1-bound input, any corpus/canonical/release/chunk change, or any uncertainty about byte identity invalidates reuse and requires a new H1 decision.
