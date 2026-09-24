# WAIT_FOR_MESA_PHASE_10 — exact model-visible context adapter

Status: `WAIT_FOR_MESA_PHASE_10`

Required fields: exact ordered model-visible context, context evidence IDs,
context hash, exact system/user prompts, provider/model identity, request
parameters, raw provider response, and parsed structured response.

Required semantics: capture the bytes/structure actually passed to the answer
model after all production formatting and truncation. The adapter may not
reconstruct context later from retrieval or ground truth.

Versioning: freeze context contract/formatter version, MESA commit, prompt
hashes, provider/model version, and serialization rules.

Fail-closed behavior: missing exact context, hash mismatch, cited ID outside
context, or reconstructed/post-hoc context makes answer scoring non-PASS.

Synchronization tests: exact order/hash, truncation boundary, prompt identity,
context/citation subset, raw-before-score ordering, and oracle-field rejection.
