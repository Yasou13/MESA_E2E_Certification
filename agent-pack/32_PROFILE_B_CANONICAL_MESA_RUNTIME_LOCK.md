# 32 — Profile B Canonical MESA Runtime Lock

## Purpose

This document fixes the canonical MESA runtime semantics for the official
Profile B run.

The agent must not choose these settings based on observed TEST results.

The exact current environment-variable/config key names must be discovered from
the live MESA `main` source and Compose/runtime configuration before launch.
If key names changed, preserve the semantic values below and record the mapping.

---

## 1. Official validation mode

The official Profile B run MUST use:

```text
MESA_MODEL_ENABLED = true
MESA_TIER3_MODE = 0
```

Meaning:

- model-backed extraction remains enabled,
- deterministic Tier-3 validation is used,
- no extra Mode-1/Mode-2 LLM validator is allowed in the official score path.

The agent must not select Mode 1 or Mode 2 for the official run.

Mode 1/2 may be exercised only as explicitly labeled supplemental diagnostics.
Their results must not be mixed into official Profile B metrics.

---

## 2. External provider gate

The official run MUST allow the configured external NVIDIA/OpenAI-compatible
provider path:

```text
MESA_EXTERNAL_PROVIDER_ENABLED = true
```

If the live MESA source uses a renamed/equivalent setting, discover it and
record the exact mapping.

A fallback to mock/local/deterministic provider is not acceptable for the
official native PASS path unless the certification contract explicitly defines
that provider as canonical. For this Profile B contract it does not.

---

## 3. Embedding identity lock

Official Profile B embedding semantics:

```text
provider  = openai_compatible / NVIDIA-compatible path
model     = nvidia/nemotron-3-embed-1b
dimension = 2048
```

Asymmetric embedding semantics are mandatory:

```text
document -> input_type=passage
query    -> input_type=query
```

The agent must verify this through the real production code path, not only by
direct provider calls.

The active embedding identity/version/revision/dimension must be recorded in
the contract freeze and determinism manifest.

No silent fallback to another embedding family is allowed.

---

## 4. Extraction identity lock

Official Profile B extraction semantics:

```text
provider = openai_compatible / NVIDIA-compatible path
model    = openai/gpt-oss-20b
language = Turkish (`tr`)
```

The real MESA extraction service must be used.

Structured extraction must return the schema expected by current MESA.

The extraction output budget must be large enough for the real structured
extraction path. The canonical minimum for this certification is:

```text
max output/completion tokens >= 4096
```

If current MESA exposes this as `MESA_EXTRACTION_MAX_TOKENS`, set it to 4096.
If the live key was renamed, discover the current key and preserve the same
semantic minimum.

Do not lower this value after observing TEST results.

---

## 5. Final-answer model lock

Official grounded-answer generation uses:

```text
model = openai/gpt-oss-20b
```

The final-answer model is separate from retrieval scoring.

It may receive only the allowed retrieved context defined by the benchmark
information barrier.

Do not substitute another model after TEST begins.

---

## 6. Provider endpoint

The canonical NVIDIA-compatible endpoint is:

```text
https://integrate.api.nvidia.com/v1
```

The exact runtime variable/key must be discovered from current MESA source.

Never write API-key values into committed config, reports or evidence.

Secrets remain external to the repository.

---

## 7. What is hard-locked vs run-frozen

### Hard-locked by this Profile B contract

- `MESA_MODEL_ENABLED=true`
- `MESA_TIER3_MODE=0`
- external provider path enabled
- Nemotron embedding model identity
- embedding dimension 2048
- passage/query asymmetric input semantics
- GPT-OSS extraction model identity
- Turkish extraction semantics
- extraction output budget >= 4096
- GPT-OSS final-answer model identity
- native MESA_Data -> MESA ingestion path

### Frozen per official RUN, but not permanently hard-coded here

These must be recorded before TEST and may not change during the RUN:

- exact timeout values,
- retry values,
- concurrency,
- batch sizes,
- top_k,
- RRF settings,
- graph max_hops,
- lane weights,
- provider SDK version,
- provider-visible revision/header,
- exact prompts,
- exact current config key names.

These operational values may need adaptation to current product/runtime
capabilities, but once the official RUN is frozen they cannot be changed
without invalidating that RUN.

---

## 8. Runtime verification before TEST

Before the first official TEST query, the agent must prove the effective
runtime values.

Do not trust only `.env`, Compose YAML or shell exports.

Verify from runtime/config introspection/logs or another reliable production
path that the effective values are:

```text
model_enabled            = true
tier3_mode               = 0
external_provider        = enabled
embedding_model          = nvidia/nemotron-3-embed-1b
embedding_dimension      = 2048
document_input_type      = passage
query_input_type         = query
extraction_model         = openai/gpt-oss-20b
extraction_language      = tr
extraction_max_tokens    >= 4096
final_answer_model       = openai/gpt-oss-20b
```

Write:

```text
runs/<RUN_ID>/mesa-runtime-lock.json
```

with the effective values and safe evidence references.

Never include secrets.

---

## 9. Docker/Compose parity

Host-shell success is not enough.

If Profile B runs MESA through Docker/Compose, all canonical semantics above
must reach the actual containers/workers.

The agent must compare:

```text
intended config
vs
Compose/container environment
vs
effective runtime config
```

Any mismatch is a preflight blocker.

Do not continue official TEST with host-only provider configuration while the
container uses defaults.

---

## 10. Drift handling

If current MESA `main` changes configuration names or removes a setting:

1. inspect live source,
2. determine the new canonical equivalent,
3. preserve the semantics of this document,
4. record the mapping in `decision_log.jsonl`,
5. update certification implementation if necessary,
6. invalidate/refreeze the RUN if already frozen.

If current MESA fundamentally changes the meaning of modes 0/1/2, do not guess.
Treat it as a methodology/runtime-contract change requiring explicit review.

---

## 11. PASS condition

The canonical MESA runtime lock passes only when:

- effective Mode 0 is proven,
- model-backed extraction remains active,
- real NVIDIA-compatible providers are active,
- Nemotron passage/query behavior is proven,
- GPT-OSS extraction is proven through MESA,
- Docker/runtime parity is proven,
- all values are included in the pre-TEST freeze,
- no TEST-driven runtime tuning occurred.

Failure to prove these conditions prevents `PROFILE_B_PASS_NATIVE`.
