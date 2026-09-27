# Remaining external contract blockers

## Phase 7 / B9 and B10 leakage

Required from MESA: a public, versioned ranked-candidate scope identity that
includes effective agent/principal plus a query-bound pre-rank exclusion audit
identity. It must prove forbidden tenant/dataset/agent/status/jurisdiction/
temporal candidates did not contribute lane rank.

Current evidence is insufficient because implementation code and internal tests
cannot serve as a current-run external certification artifact. E2E rejects the
gap as `BLOCKED_BY_MESA_CONTRACT`; it does not report tenant leakage as zero.

## Phase 8/9 / B11

Required from MESA: stable public graph path IDs and a supported public
graph-ON/graph-OFF evaluation contract with a stable pair identity over the
same query, dataset, MESA SHA, storage/graph snapshot and non-graph settings.

Current provenance demonstrates graph participation but cannot establish a
legitimate matched causal ablation. E2E rejects internal monkey-patching and
test-only graph substitution and reports `BLOCKED_BY_MESA_CONTRACT`.

These are the only confirmed external blockers found in the four original
`WAIT_FOR_MESA` areas. Phase 1 and Phase 10 are implemented against existing
native contracts.

