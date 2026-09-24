# harness/

This directory owns deterministic certification code: runners, validators, scorers, evidence writers, and self-tests.

## Harness principles

- Product behavior is tested through real public/native paths whenever a hard gate requires them.
- Mocked tests may reproduce a bug but cannot substitute for live hard-gate evidence.
- Infrastructure/provider failures are not retrieval misses.
- Retrieval grading is provenance/evidence-ID based, not semantic vibes.
- Final-answer grading should be deterministic from required facts, evidence IDs, forbidden claims, and abstention rules.
- The same LLM being tested must never be the sole judge of its own correctness.
- Every scorer must have small deterministic unit tests before the final run.

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
