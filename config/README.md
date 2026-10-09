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

## Executable gate configuration

`profile-b-gates.json` encodes the current B10 and B12 numerical thresholds
from the agent pack and lists the complete mandatory B0–B14 gate set. B12
remains hard under the current repository contract. Any future change to that
methodology requires an explicit human decision and a new pre-run freeze.

The same file is the canonical machine-readable Profile B contract for:

- the 8 GiB hard RAM minimum, 12 GiB recommended RAM, and 30 GiB disk minimum;
- the sealed top-5 retrieval set used to construct official answer context;
- the selected embedding, extraction, and answer provider/model identities:
  - **Embedding**: Ollama (`alibayram/embeddingmagibu-200m:latest`), dimension 768, L2 normalization, runtime-resolved digest.
  - **Extraction**: Ollama (`qwen3.5:9b-q4_K_M`), Turkish (`tr`), minimum max tokens 4096, Q4_K_M quantization, runtime-resolved digest.
  - **Answer**: Ollama (`qwen3.5:9b-q4_K_M`), Q4_K_M quantization, runtime-resolved digest.
  - **Endpoint**: Runtime-configurable provider base URL. The framework enforces strict comparison between frozen contract and observed runtime identities without hard-coding local test IP addresses.

The recommended RAM value is operational guidance, not a harder B1 threshold.
Gate loading fails if B1 drifts from the canonical resource values.
