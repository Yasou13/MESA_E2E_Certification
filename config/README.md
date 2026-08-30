# config/

This directory owns the **non-secret certification configuration contract** and frozen benchmark configuration artifacts.

## Rules

- Never store API keys, bearer tokens, private certificates, or secret env files here.
- Discover live MESA/MESA_Data config names from current source before generating runtime config.
- The TEST configuration must be frozen and hashed before the first TEST retrieval call.
- Once TEST begins, changing retrieval/model/prompt/scoring configuration invalidates the run.
- DEV tuning is allowed only before TEST freeze and only against the DEV set.

## Freeze at minimum

Record and hash:

- MESA/MESA_Data/certification SHAs;
- container/image digest and Compose file hash;
- embedding provider/model/version/dimension/normalization/input-type behavior;
- extraction provider/model/language/max-token setting;
- answer-generation provider/model/prompt version;
- retrieval top-k;
- lane configuration/weights;
- RRF constants;
- graph enablement/max hops/limits;
- lexical/vector/assertion settings;
- filters/scoping;
- timeouts/retry policy relevant to result validity;
- scorer version/hash;
- corpus/release/GT hashes.

See `../agent-pack/13_BENCHMARK_CONFIG_FREEZE.md` for the authoritative policy.

