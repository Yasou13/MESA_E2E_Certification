> **Profile B Autonomous Agent Pack v3.0**  
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 16 — GRAPH PROOF AND ABLATION

## Why code inspection is insufficient

A Kùzu database can be populated while public retrieval ignores it. A graph function can be called while all useful results come from vector/BM25. Profile B therefore requires both **origin evidence** and **causal contribution**.

## Runtime graph-use proof

From current MESA public `/v4/memory/search` results, inspect the supported retrieval-provenance fields. Archive baseline exposed origin names plus graph hop/seed/path assertion IDs.

For each predesignated REL query record:

```text
graph origin present?
graph hop count
graph seed entity ID
graph path assertion IDs
returned source chunk/document provenance
rank/final score
```

Validate path assertion IDs exist in the current Kùzu/canonical assertion state using a read-only diagnostic path. Do not mutate graph to make the path valid.

## Causal graph-OFF shadow ablation

The benchmark config remains frozen and public product behavior remains unchanged. Build a **read-only shadow evaluation** over the same finalized storage snapshot/query set with the graph lane disabled/empty while vector, lexical and assertion lanes are held constant.

Preferred methods, in order:

1. use an existing supported read-only ablation/eval hook if current MESA has one that runs the real retrieval lane data;
2. instantiate the current retrieval/DAO against a copied read-only storage snapshot and substitute only the graph provider with a deterministic empty/non-operational graph search for the shadow run;
3. add a test-only/evaluation hook only if absolutely necessary, with regression tests and a new certification run.

Do not patch production search during the scored ON run. Do not use MESA's synthetic lane-fusion unit/CI ablation as the only graph proof.

## Comparison

For the exact same 10 REL queries compare ON vs OFF:

- top-5 expected evidence groups;
- complete-evidence@5;
- first relevant rank/MRR;
- result IDs/ranks;
- graph-origin paths.

Hard proof requires:

```text
real graph operational
>=3/10 REL queries with graph-origin contribution in top-5, where dataset design supports it
>=1 REL query with a causal rank/evidence/result difference when graph is removed
no graph backend error hidden as empty lane
```

If the frozen source-first REL design naturally produces fewer graph-origin queries, do not rewrite TEST questions after seeing results. Report B11 fail with evidence.

## Graph metric interpretation

Graph is not required to improve every query. The hard purpose is to prove the lane is real and causally participates in legal retrieval. Overall retrieval thresholds remain independent hard gates.

