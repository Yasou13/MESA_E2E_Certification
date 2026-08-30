> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 13 — BENCHMARK CONFIG FREEZE

## Why this exists

A benchmark is invalid if the agent repeatedly changes retrieval settings against the scored TEST set until it passes.

## DEV-only tuning

The 12 DEV questions may be used to catch obvious configuration errors and choose one reasonable retrieval configuration. Record every DEV attempt. Do not optimize aggressively; the purpose is configuration validation, not model leaderboard tuning.

## Freeze before TEST

Before the first TEST query, serialize and hash every setting that can influence retrieval or answer generation. At minimum discover and include current equivalents of:

### Retrieval

```text
public API route/mode
query text normalization/decomposition
limit/top_k (primary = 5 for scoring)
vector model/provider/version/dimension/normalization
lexical/BM25 settings
RRF constant/order/weights if configurable
graph lane enabled state
max graph hops
assertion lane settings
jurisdiction/temporal filters (Profile B defaults should be explicit)
any reranker/legal factor settings
session/dataset scope
```

### Extraction / ingestion

```text
extraction provider/model/lang/max_tokens/temperature or current defaults
Tier3 validation mode
chunking limit and MESA_Data chunk plan version
embedding identity
```

### Final answer

```text
model/endpoint
answer prompt version/hash
max tokens
temperature
context construction rules
abstention phrase
```

### Runtime

```text
MESA SHA
MESA_Data SHA
container image digest if available
Compose rendered config hash with secrets redacted
GT hashes
corpus/release manifest hashes
```

## Freeze artifact

Create a normalized JSON/YAML config artifact plus SHA-256. Also preserve a redacted `docker compose config` output. Secret fields must be replaced with `<REDACTED_PRESENT>` before hashing/reporting.

## After freeze

During TEST, forbidden changes include:

- top_k/limit;
- RRF/weights/constant;
- graph hops/toggle;
- query rewrite behavior;
- prompts;
- model/timeout/token budget;
- source corpus;
- qrels;
- filters;
- scoring code.

If a genuine bug requires one of these changes, fix it, invalidate the run, create a new RUN_ID, repeat DEV/freeze, then run TEST again. The old failed TEST remains evidence.


<!-- V3.1_IDENTITY_MAP_FREEZE -->
## Identity mapping freeze boundary

The benchmark config freeze must include the **identity-mapping algorithm/version and publisher mapping contract**. The concrete `identity_map.jsonl` cannot be complete until native delivery creates/reconciles MESA identities, so its SHA is frozen separately immediately after Phase 6 and before any TEST retrieval. Record that SHA in the run manifest and final config/evidence index. No TEST scoring may begin without a valid frozen map.

## Complete certification contract freeze

The freeze must include not only runtime/model config but also:

- certification Git SHA,
- agent-pack checksum manifest,
- harness/scorer hashes,
- TEST/DEV query hashes,
- ground-truth/qrel hashes,
- identity-map hash,
- corpus/release hash,
- verdict/threshold rules.

Write `runs/<RUN_ID>/contract-freeze.json` before the first official TEST
query.

Any material change after this point invalidates the run.
