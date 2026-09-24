# WAIT_FOR_MESA_PHASE_7 — scope/rank adversarial adapter

Status: `WAIT_FOR_MESA_PHASE_7`

Required fields: tenant, dataset, agent/principal, status, jurisdiction,
version/effective-date, and stale/current identity for every ranked candidate.

Required semantics: forbidden-scope candidates are excluded before rank
contribution and cannot leak through context, catalog, document, revision, or
chunk paths.

Versioning: freeze the public filtering contract version and MESA commit with
the adversarial fixture version.

Fail-closed behavior: missing scope identity, ambiguous effective date, or
unverifiable filter order makes B9 unverified/failed; it cannot be interpreted
as zero leakage.

Synchronization tests: cross-tenant/dataset/agent negatives, inactive status,
wrong jurisdiction, stale version, effective-date boundary, and pre-rank
exclusion proof.
