# WAIT_FOR_MESA_PHASE_1 — evidence-level retrieval adapter

Status: `WAIT_FOR_MESA_PHASE_1`

Required fields: versioned first-class matched-evidence ID, stable public result
ID, rank, score, bounded text, and separately labelled support/debug
provenance.

Required semantics: rank metrics use only first-class matched evidence. Broad
entity/document provenance must never inherit the result rank or create a HIT.

Versioning: the response and evidence contract need explicit schema versions;
the exact MESA commit and contract version are frozen in the runtime lock.

Fail-closed behavior: unknown IDs, missing matched-evidence fields, mixed
versions, or provenance-only evidence produce `MAPPING_INTEGRITY_ERROR` or an
unverified gate, never MISS/HIT.

Synchronization tests: entity-wide provenance false-hit, exact evidence at
ranks 1/5, unknown mapping, malformed result, REL group coverage, and stable
serialization.
