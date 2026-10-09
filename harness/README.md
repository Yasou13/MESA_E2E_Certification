# harness/

This directory owns deterministic certification code: runners, validators, scorers, evidence writers, and self-tests.

## Harness principles

- Product behavior is tested through real public/native paths whenever a hard gate requires them.
- Mocked tests may reproduce a bug but cannot substitute for live hard-gate evidence.
- Infrastructure/provider failures are not retrieval misses.
- Retrieval grading uses only the first-class matched-evidence ID, not semantic
  similarity or broad entity support/debug provenance.
- Final-answer grading should be deterministic from required facts, evidence IDs, forbidden claims, and abstention rules.
- The same LLM being tested must never be the sole judge of its own correctness.
- Every scorer must have small deterministic unit tests before the final run.

For the official Profile B path, the answer-visible context is built
deterministically from the sealed top-5 retrieval response. Each candidate is
bound by rank, candidate/evidence/chunk/document identity, origin, text, and a
budget inclusion decision. An independent session-context lookup is not an
allowed source for answer evidence.

The official Profile B provider contract validates embedding (e.g., Ollama
`alibayram/embeddingmagibu-200m:latest`, 768-dim, L2 normalized) and answer
completion (e.g., Ollama `qwen3.5:9b-q4_K_M`, Q4_K_M quantization) specifications,
including runtime-resolved model digests. Model endpoints are strictly
runtime-configurable via CLI or environment variable, avoiding hardcoded target IPs.

A harness/scorer change after a run starts invalidates that run.

## Reproducible developer entrypoints

```bash
uv sync --locked --all-groups
uv run --locked pytest
uv run --locked python -O -m harness.self_test
```

`uv.lock` is the dependency authority for CI and local harness development.
The optimized self-test command is mandatory because the production self-test
must not depend on removable Python `assert` statements.

## Raw-first execution evidence

New runs use separate `raw/retrieval`, `raw/answers`, `scored/retrieval`, and
`scored/answers` lanes. Raw records and their SHA sidecars must exist and pass
the sealed oracle audit before scored output can be written. Existing run
directories without an E2E layout marker are treated as immutable/unowned.

Official B4, B6, B7, and B8 inputs must also be registered as artifacts of the
current trusted execution session. B5 approval must match the approval hash in
the verified freeze. Hand-authored or stale JSON can be useful diagnostically,
but cannot produce an official PASS.

## Operational evidence and release finalization

`harness.operations` defines strict pre/post health snapshots, resource samples,
pressure events, and the secret-free runtime lock. OOM, required-service restart,
critical pressure, or provider usage above twice the frozen expectation fails the
resource summary; absent telemetry remains `UNVERIFIED`.

`harness.finalizer` accepts only the complete sanitized release file set. It
checks RUN_ID/schema coherence and sensitive fields, creates a deterministic
`SHA256SUMS.txt`, and promotes the bundle with an atomic same-filesystem rename.
Incomplete, unsafe, or already-existing destinations fail closed.
