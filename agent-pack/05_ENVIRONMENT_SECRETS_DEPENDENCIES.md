> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 05 — ENVIRONMENT, SECRETS AND DEPENDENCIES

## Minimum VM gate

Full Profile B is not allowed on the temporary 4 GiB setup. Hard preflight:

```text
RAM total: >= 8 GiB hard minimum
Recommended RAM: 12 GiB+
Disk free before run: >= 30 GiB
Docker: available and usable by current user
uv: available
Network/DNS/TLS: functional for official sources + NVIDIA + GitHub
System clock: sane
```

Record swap size and free memory. Do not disable OOM protection to force the run through.

## Secret locations

Expected NVIDIA secret file:

```text
~/mesa-cert/secrets/nvidia.env
```

Never print it. Never run `env`, `set`, `export -p`, shell tracing (`set -x`), or diagnostics that dump all environment variables after secrets are loaded.

Prefer narrowly checking presence:

```bash
test -n "${NVIDIA_API_KEY:-}" && echo NVIDIA_API_KEY_PRESENT
```

Never include token prefixes or character counts if that could fingerprint a secret.

## Secret mapping

The live code decides exact names. Archive baseline used combinations of:

```text
LLM_API_KEY
MESA_EMBEDDING_API_KEY
MESA_DATA_MESA_API_KEY
MESA_API_KEY
```

Map values in process environment only. Evidence may record only boolean presence and a secret-source label such as `nvidia.env`, never the value.

## Dependency install

MESA local probes should use locked dependencies and adapter extras when needed:

```bash
uv sync --frozen --extra adapters
```

The supplied MESA Dockerfile already built/installed `ml,adapters`; verify the final production image imports `openai` inside the container rather than assuming it.

MESA_Data baseline:

```bash
uv sync --frozen
```

Do not casually update the lockfile/dependency versions to fix a runtime problem. Dependency changes are product changes and trigger a new run.

## Runtime identity manifest

Record at run start:

- OS/release/kernel;
- architecture;
- Python and uv versions per repo;
- Docker and Compose versions;
- MESA and MESA_Data SHA/version;
- OpenAI SDK version in host MESA venv and production container;
- LanceDB/PyArrow/Kùzu versions inside actual runtime;
- total/free RAM, swap, disk;
- NVIDIA endpoint/model labels;
- UTC timestamps of provider probes;
- any provider revision/request ID/response metadata safely exposed, without credentials.

Remote NVIDIA aliases may change server-side. If no immutable model revision is exposed, record this explicitly as a reproducibility limitation rather than pretending the model binary is frozen.

