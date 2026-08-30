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

