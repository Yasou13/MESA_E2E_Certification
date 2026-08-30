> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 26 — EXPECTED OUTPUTS AND ASSERTIONS

This file prevents “command exited 0” from being confused with “gate passed.” Exact field names may evolve; discover the live contract and map it to these semantic assertions.

## Provider assertions

### Nemotron document probe

Expected semantic output:

```text
provider/model = intended openai-compatible Nemotron identity
dimension = 2048
all values finite = true
normalized/norm contract = true
request semantic input_type = passage
```

### Nemotron query probe

```text
dimension = 2048
finite = true
request semantic input_type = query
same-text passage vector != query vector
```

Identical passage/query vectors or missing asymmetric request semantics is a fail even if HTTP returns 200.

### GPT-OSS extraction probe

Expected:

```text
actual MESA extraction adapter selected
actual model = openai/gpt-oss-20b
language = tr
bounded max-token budget resolved (archive baseline 4096)
structured response validates under current FactExtractionResponse equivalent
source spans are exact source substrings
provider timeout is reported as provider unavailable/timeout, not ordinary JSON corruption
```

## Production container assertions

A rendered/redacted Compose/runtime check must prove the container has the same frozen model/config identity as the host probe. Presence of a value in `.env` does not prove it reached the container.

Expected health/capability semantics:

```text
service healthy
authentication active
vector retrieval operational
graph/Kùzu operational
projection consumer/writes operational
```

If a capability is missing/false, do not benchmark and hope it recovers.

## MESA_Data assertions

For selected legal documents:

```text
raw artifact exists
raw SHA-256 verifies
canonical content non-empty
no replacement-character/mojibake blocker
quality = PASS for release eligibility
validation = valid
privacy acceptable
approval = approved before release build
coverage evidence present
```

Windows-1254/cp1254 content must preserve Turkish characters such as `ı, İ, ğ, ş, ç, ö, ü`; the exact fixture assertions come from the current tests/source.

## Release assertions

A valid release is not merely a directory. Expected:

```text
release build completed
product verifier PASS
release manifest exists and hashes verify
publisher index/selected versions match H1-approved membership
planned SourceChunk count deterministic
same input rebuilt under same code/config yields same chunk identity/content hashes where product contract promises determinism
```

## Native publisher canary assertions

Against real MESA:

```text
MESA_Data native product publisher initiates request(s)
no guessed/mock route
MESA auth/RBAC/session contract satisfied
remote mutation ID captured for async ingest when current contract uses mutations
terminal state = COMMITTED or documented legitimate idempotent already-committed outcome
public MESA search returns canary
returned provenance maps to exact MESA_Data document/version/chunk/source identity
native retry does not create duplicate logical content
```

A 200/201/202 alone is not enough.

## Full delivery assertions

Reconcile exact counts:

```text
planned_chunks
= newly_committed + legitimately_precommitted_or_skipped
and failed = 0
and rejected = 0
and unexplained = 0
```

If current state machine contains additional terminal states, classify them explicitly; do not silently count unknown as committed.

## Restart assertion

After service restart with the same persistent run volume:

```text
health returns
fixed sample queries still find expected provenance
mutation/source catalog remains coherent
no re-ingestion required merely to see prior committed data
```

## Idempotency assertion

Repeat exact native delivery/input identity:

```text
logical source chunk count unchanged
logical fact/projection duplication absent
ledger recognizes committed/skip/duplicate semantics
stable idempotency key remains stable for exact same content/scope
```

## Isolation assertions

Unauthorized Tenant A → Tenant B operations must return safe denial/filter behavior and **zero Tenant B source content/provenance**. The exact safe status can be 403/404/filtered empty according to the current API.

Any leaked protected text/provenance = hard fail.

## Retrieval assertions

Each valid TEST call:

```text
HTTP/runtime success
exact frozen query text
limit/top_k = frozen value (primary 5)
results preserve public provenance
no hidden fallback provider/config drift
```

Metrics then satisfy the thresholds in `06_PROFILE_B_OBJECTIVE_GATES_VERDICTS.md`.

## Graph assertions

For graph-origin hits:

```text
origin includes graph/current equivalent
graph hop/path fields internally valid
path assertion IDs exist
same frozen REL query under graph-OFF shadow changes at least one relevant rank/result/evidence outcome across REL set
```

Merely finding rows in Kùzu is not sufficient.

## Final answer assertions

For answerable queries counted PASS:

```text
insufficient_evidence = false
all cited chunk IDs were actually retrieved
required facts satisfied
no forbidden material claim
no material unsupported claim
```

For NO_ANSWER counted PASS:

```text
insufficient_evidence = true
answer = YETERSİZ KANIT
no substantive claim appended
no fabricated evidence
```

## CI/final assertions

Before `PROFILE_B_PASS_NATIVE`:

```text
MESA exact final SHA local CI-equivalent PASS
MESA_Data exact final SHA local CI-equivalent PASS
GitHub Actions for exact final branch SHAs green
worktrees clean
GT hash unchanged since freeze
benchmark config hash unchanged since freeze
release/H1 hashes consistent
no code changes after final run start
SHA256SUMS verification PASS
```

