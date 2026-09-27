# Phase 8/9 — graph provenance and causal ablation adapter

Status: `BLOCKED_BY_MESA_CONTRACT`

Verified against read-only MESA checkout
`194f7b2b439ae6b9bc0f420a42a98eff1f4db2d0`.

## What MESA currently exposes

`MemoryDAO.search_v4_memory` exposes real graph participation through
`retrieval_provenance`, including origins, lane ranks, raw scores, graph paths,
path assertion IDs, entity IDs, edge directions, predicates, graph score and
support counts. E2E validates path/assertion alignment, direction, evidence
identity and duplicate-path behavior in `harness/mesa_adapters.py`.

## Minimal missing public contract

The native public runtime does not expose:

- a stable `graph_path_id` for each returned graph path; or
- a supported public graph-ON/graph-OFF evaluation switch plus pair identity
  that holds query, dataset, MESA SHA, snapshot and all non-graph settings
  constant.

Internal DAO substitution, monkey-patching or test-only empty graph providers
are not accepted as official evidence. Consequently B11 runtime proof remains
blocked even though all E2E-side validation and pairing code is implemented.

## E2E behavior

The B11 producer rejects unmatched pairs and logging-only graph claims,
validates stable path evidence, and separately counts positive utility, neutral
effect and harm. Worse evidence coverage or rank is harm and cannot prove graph
benefit. Missing native capabilities yield `BLOCKED_BY_MESA_CONTRACT`.

Covered by `tests/test_mesa_adapters.py` and `tests/test_metric_producers.py`.
