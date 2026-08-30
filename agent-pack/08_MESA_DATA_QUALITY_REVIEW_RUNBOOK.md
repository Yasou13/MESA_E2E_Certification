> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 08 — MESA_DATA QUALITY AND REVIEW RUNBOOK

## Goal

Produce a reproducible approved corpus from real official sources while proving raw fidelity, Turkish decoding, canonical coverage and release integrity. The agent should use MESA_Data's existing mechanisms rather than inventing a parallel ETL system.

## Start clean per RUN_ID

Set a run-specific data root, for example:

```text
<CERT_ROOT>/datasets/runtime/<RUN_ID>/mesa-data
```

Initialize/migrate using the live CLI discovered with `uv run mesa-data --help`.

## Source policy

Use only configured official/approved source mechanisms. Archive baseline showed:

- `resmi_gazete`: approved web/automated;
- `mevzuat`: manual official source;
- 12 seed legislation entries including Constitution, 4857, 6098, 6100, 5237, 5271, 6698, etc.;
- disabled/unapproved sources must not be silently enabled just to hit corpus size.

Every selected source must retain URL/source identifier, acquisition timestamp, raw SHA-256 and source type.

## Encoding gate

Revalidate the Windows-1254 fix against at least:

- a known cp1254/Windows-1254 HTML fixture from tests;
- one real selected source if such encoding occurs in the corpus;
- UTF-8 content;
- mojibake detection.

A canonical source containing obvious byte-loss artifacts, `�`, common Turkish mojibake, or missing legal words due to decoding is not approvable.

## Raw↔canonical integrity

For every document record:

- raw artifact exists and raw SHA verifies;
- raw bytes are immutable within the run;
- detected/declared charset evidence is retained where meaningful;
- canonical non-empty content exists;
- canonical/source identifiers are stable;
- source spans/record offsets stay within canonical bounds;
- release references the exact approved version.

## Parsing coverage / data-loss guard

Use the product's existing `ParsingCoverage`/quality logic (or current equivalent). Do not create a second magic ratio solely for certification.

Additionally summarize per document:

```text
raw byte size
canonical character count
article count
coverage ratio
uncovered character count
largest uncovered gap
quality status
encoding/mojibake warnings
```

Any product `BLOCK` is a hard exclusion/blocker. Any `REVIEW` or large unexplained gap must be in the H1 bundle. If the existing coverage gate demonstrably misses material legal text loss on a selected document, treat it as a MESA_Data product bug: reproduce, fix minimally, regression-test, invalidate the run and restart.

## Review operations

Revalidate:

- single-record review;
- version-level bulk approve/reject;
- current-version semantics;
- raw HTML/text versus canonical side-by-side display/endpoint;
- XSS-safe rendering if web review is used.

The agent may automatically prepare/recommend review state but may not fabricate the human H1 approval.

## Release and the single human checkpoint

After data quality preparation:

1. select the deterministic corpus according to `10_CORPUS_DESIGN.md`;
2. split selected versions into already-approved (including safe auto-approved) and manual-review-required;
3. generate the H1A review bundle for the exact selected version/canonical hashes and STOP;
4. during the same H1 checkpoint, the human approves/rejects any selected manual-review-required versions; rejected versions are replaced only from the pre-ranked deterministic candidate list and must be shown before acceptance;
5. once every selected version is product-eligible (`quality=PASS`, valid, privacy-acceptable, approved), build the immutable release;
6. verify the release with the product verifier;
7. capture release ID, manifest SHA, counts, frozen publisher index/chunk-plan inputs;
8. present H1B final release hash confirmation in the **same human checkpoint**; only explicit H1B approval authorizes full delivery.

This ordering matches the inspected MESA_Data release contract, which only emits records from approved, valid, quality-PASS current versions. It preserves the product goal that the human is involved only at the final review/approval checkpoint.

Local staging import is diagnostic/development only and is not the native MESA publisher gate.

