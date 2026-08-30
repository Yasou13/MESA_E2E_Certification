> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 07 — MESA RUNTIME AND PROVIDER PREFLIGHT

The goal is to prove the models work **through MESA's current production paths**, not merely through the NVIDIA endpoint.

## Step A — static discovery

Before starting services inspect current live code for:

- embedding backend factory and Nemotron asymmetric handling;
- `FactExtractionService` or its current replacement;
- adapter factory/config aliases;
- Dockerfile dependency extras;
- Compose environment propagation;
- V4 health/capability/session/insert/search/mutation routes;
- Kùzu provider and retrieval graph lane;
- admin bootstrap/authorization CLI.

Capture exact files/functions in evidence.

## Step B — locked host probes

Using the MESA environment and secret file, verify:

### Nemotron

Expected baseline:

```text
provider=openai_compatible
model=nvidia/nemotron-3-embed-1b
version=nemotron-qpass-v1
dimension=2048
base=https://integrate.api.nvidia.com/v1
```

Through MESA's embedding service/factory:

1. `embed_document(text)` returns finite normalized 2048 vector;
2. `embed_query(text)` returns finite normalized 2048 vector;
3. the document and query vectors for the same nontrivial text are not identical;
4. request path actually maps document→`passage` and query→`query` (verify code + behavior/test instrumentation without logging credentials).

### GPT-OSS basic adapter

Through MESA's selected `OpenAICompatibleAdapter`/current equivalent:

- plain completion returns expected marker in 3 bounded attempts;
- simple Pydantic structured output validates;
- no provider-side failure is misclassified as ordinary malformed JSON.

### Real fact extraction

Use the actual production extraction service with a small Turkish legal paragraph. Verify:

- configured provider/model/lang/max-token budget;
- valid structured response;
- at least one semantically plausible fact;
- non-empty `source_span` values are exact substrings of source text;
- malformed/provider failure classification is truthful.

Archive baseline expected `MESA_EXTRACTION_MAX_TOKENS=4096`; do not reduce it just to save tokens if the current production contract requires reasoning headroom.

## Step C — Docker production parity gate

This is mandatory. Build/start the actual V4 image/Compose configuration with explicit frozen Profile B variables. Inspect safely inside the container (presence/labels only, no secret values) and prove it sees the expected values.

At minimum the frozen configuration must cover current equivalents of:

```text
MESA_MODEL_ENABLED=true
MESA_EXTERNAL_PROVIDER_ENABLED=true
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL_NAME=openai/gpt-oss-20b
LLM_TIMEOUT_SECONDS=<frozen bounded value>
MESA_EMBEDDING_PROVIDER=openai_compatible
MESA_EXTERNAL_EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b
MESA_EMBEDDING_DIMENSION=2048
MESA_EMBEDDING_VERSION=nemotron-qpass-v1
MESA_EMBEDDING_BASE_URL=https://integrate.api.nvidia.com/v1
MESA_EXTRACTION_PROVIDER=openai_compatible
MESA_EXTRACTION_MODEL=openai/gpt-oss-20b
MESA_EXTRACTION_LANG=tr
MESA_EXTRACTION_MAX_TOKENS=4096
MESA_TIER3_MODE=0
```

API keys must be present but never printed.

`MESA_TIER3_MODE=0` isolates Profile B from unrelated Tier-3 dual-validator cost while still exercising real fact extraction, unless the current architecture proves that this would disable the extraction under test. Record the resolved validation capability.

If Compose does not pass a required variable, that is a deployment defect. Fix Compose/config contract minimally and restart the run.

## Step D — capability and canary

Using authenticated V4 API:

- `GET /health` (or current discovered health endpoint) succeeds;
- V4 capability reports vector and graph operational where current API exposes them;
- an isolated canary session can ingest one technical test record, wait to COMMITTED, search it, and show expected provenance;
- restart the service and find the canary again before deleting/purging the dedicated canary scope if supported.

The canary may use a dedicated certification tenant/dataset and is covered by the user's instruction to run certification; it must not publish the full legal corpus before H1.

## Timeout policy

Do not interpret one remote timeout as a product bug. Provider call limits and retry rules are in `20_RESOURCE_AND_PROVIDER_BUDGETS.md`. If 60 seconds is empirically insufficient for a real structured reasoning call, a bounded value such as 120 seconds may be selected during DEV/preflight and frozen before TEST. Do not tune timeout based on TEST outputs.


## Profile B canonical runtime values

The official Profile B run MUST use the semantics in
`32_PROFILE_B_CANONICAL_MESA_RUNTIME_LOCK.md`.

At minimum prove the effective runtime has:

```text
MESA_MODEL_ENABLED=true
MESA_TIER3_MODE=0
external provider enabled
nvidia/nemotron-3-embed-1b
embedding dimension 2048
document input_type=passage
query input_type=query
openai/gpt-oss-20b extraction
Turkish extraction
extraction max tokens >= 4096
```

Do not rely on host exports alone; verify effective container/runtime values.
