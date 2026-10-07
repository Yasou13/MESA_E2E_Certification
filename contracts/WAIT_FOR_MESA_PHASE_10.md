# Phase 10 — exact model-visible context and answer capture

Status: `IMPLEMENTED`

Verified against read-only MESA checkout
`194f7b2b439ae6b9bc0f420a42a98eff1f4db2d0`.

## Ownership and certification contract

MESA owns retrieval and returns the ranked evidence spans and stable candidate,
assertion, chunk, document, scope, and graph provenance needed by Profile B.
The public session-context endpoint performs an independent context retrieval,
so it is not an admissible source for the official top-5-bound answer lane.

For official Profile B scoring, E2E deterministically formats and budgets the
exact sealed `POST /v4/memory/search` candidates. It does not fetch additional
memories. MESA has no public final-answer endpoint, so E2E then owns the frozen
OpenAI-compatible answer-provider boundary.

## E2E binding

- `build_sealed_retrieval_context` accepts a normalized sealed retrieval capture
  and records every candidate's rank, candidate/evidence/assertion/chunk/document
  identity, retrieval origins, inclusion decision, and budget rejection reason.
- `execute_answer_and_persist` constructs the exact final request and calls the
  configured transport once, with no hidden retry or GT/oracle fields.
- `CertifiedAnswerExecutionCapture` seals exact context, allowed retrieval and
  included evidence IDs, candidate bindings, retrieval response hash, prompts,
  provider/model/parameters, request and response hashes, raw response, parsed
  response, context contract version, run identity and MESA SHA before scoring.
- `official_scoring.py` accepts only the frozen context contract and rejects any
  allowed or included evidence identity that differs from the sealed top-5.

Covered by `tests/test_mesa_adapters.py` and
`tests/test_official_scoring_transaction.py`, including order/hash tampering,
oracle-field injection and out-of-context citation failure.
