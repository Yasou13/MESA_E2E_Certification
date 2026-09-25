# ground-truth/

Ground truth must be independent from MESA retrieval, MESA embeddings, graph outputs, extraction outputs, and final answer outputs.

## Authoring order

Use this causal order:

```text
approved canonical source
→ exact evidence span/chunk identity
→ required evidence groups
→ required facts
→ acceptable answer constraints
→ forbidden claims
→ final query wording
```

Never reverse this process by asking MESA for an answer and then writing qrels around what it returned.

## Sets

Maintain separate DEV and TEST sets. Current design target:

- DEV: 12 queries for pre-freeze tuning/debugging;
- TEST: 80 frozen queries.

TEST composition is governed by `../agent-pack/10_CORPUS_DESIGN.md` and `12_GROUND_TRUTH_FREEZE.md`.

## Current historical TEST role

The exposed `RUN-20260901T005200Z-p8b03` TEST/qrels/results are a
qualification and regression benchmark. They are not a future hidden final
holdout.

The final Profile B v2 holdout must follow `HOLDOUT_POLICY.md`. Plaintext final
queries, qrels, required facts, or gold evidence IDs must never be committed to
this public repository.

## Human audit policy status

The hardening harness can deterministically prepare the recommended sample of
100% REL, 100% NO_ANSWER, and 20% SINGLE items. This percentage remains a
recommendation pending explicit human methodology approval. Generated plans
remain `HUMAN_REVIEW_REQUIRED` until domain-review records cover the sample.
