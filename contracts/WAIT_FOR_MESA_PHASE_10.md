# Phase 10 — exact model-visible context and answer capture

Status: `IMPLEMENTED`

Verified against read-only MESA checkout
`194f7b2b439ae6b9bc0f420a42a98eff1f4db2d0`.

## Ownership and native contract

MESA owns context construction, not the Profile B final answer call.
`mesa_memory/context_builder.py::ContextBuilder.build_context` returns the exact
post-format/post-budget `formatted_context` and the matching
`model_visible_memories`. Public `GET /v4/sessions/{session_id}/context` returns
that exact string as `context` with canonical visible memories and session,
tenant, agent and dataset identity.

MESA has no public final-answer endpoint. E2E therefore owns the final provider
boundary. This is not a compatibility shim: E2E consumes MESA's exact context
and makes the real OpenAI-compatible completion request itself.

## E2E binding

- `normalize_context_response` validates the context response, ordered evidence
  identity, `v4` capability identity and frozen MESA commit.
- `execute_answer_and_persist` constructs the exact final request and calls the
  configured transport once, with no hidden retry or GT/oracle fields.
- `CertifiedAnswerExecutionCapture` seals exact context, evidence IDs, prompts,
  provider/model/parameters, request and response hashes, raw response, parsed
  response, context contract version, run identity and MESA SHA before scoring.
- `official_scoring.py` accepts only this v2 capture and rejects citations
  outside its exact model-visible context.

Covered by `tests/test_mesa_adapters.py` and
`tests/test_official_scoring_transaction.py`, including order/hash tampering,
oracle-field injection and out-of-context citation failure.
