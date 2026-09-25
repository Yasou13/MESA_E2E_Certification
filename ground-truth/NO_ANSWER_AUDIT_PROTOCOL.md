# NO_ANSWER source-side audit protocol

Every NO_ANSWER item requires a human/domain audit record before freeze. The
auditor searches the approved canonical source inventory using the frozen
corpus manifest and records the sources/protocol inspected, conclusion, notes,
identity, UTC timestamp, and corpus-manifest hash.

MESA retrieval results, graph output, answer output, or scorer status must not
be used as authority for whether the corpus can answer the question. The
executable `NoAnswerAuditRecord` schema enforces
`mesa_retrieval_used_as_authority=false` and the validator requires one
resolved record per NO_ANSWER item.
