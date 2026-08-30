> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 24 — QUICK COMMAND / DISCOVERY MAP

This is a discovery aid, not an authority. Run `--help`, inspect current code and record the actual command before use.

## MESA

```bash
cd "$MESA_REPO"
git status --short
git rev-parse HEAD
uv sync --frozen --extra adapters
uv run python -V
uv run mesa-v4-admin --help
make help 2>/dev/null || true
make test-local
# production build/run uses current docker-compose.v4.yml after rendered-config inspection
```

Archive source exposed client methods/routes conceptually equivalent to:

```text
POST /v4/catalog/workspaces
POST /v4/catalog/datasets
POST /v4/catalog/documents
POST /v4/catalog/revisions
POST /v4/sessions/start
POST /v4/memory/insert
POST /v4/memory/search
GET  /v4/mutations/{id}
GET  /health
```

Always discover from live OpenAPI/current router before scripting.

## MESA_Data

```bash
cd "$MESA_REPO"_Data
git status --short
git rev-parse HEAD
uv sync --frozen
uv run mesa-data --help
uv run mesa-data doctor
uv run mesa-data audit
uv run mesa-data harvest --help
uv run mesa-data review --help
uv run mesa-data release --help
uv run mesa-data web --help
```

Archive baseline examples:

```bash
uv run mesa-data init
uv run mesa-data migrate
uv run mesa-data harvest init
uv run mesa-data harvest config-check
uv run mesa-data harvest discover --source resmi_gazete
uv run mesa-data harvest run --once --limit 25
uv run mesa-data review list --status pending
uv run mesa-data release build --release-id <id>
uv run mesa-data release verify --release-id <id>
```

The real MESA publisher was primarily exposed through product operations/web APIs in the inspected archive; discover whether the current live branch now has a CLI command. Calling the publisher engine from a certification integration test is acceptable only if it is the same product engine used by the UI/operations layer and does not bypass its release/preflight/ledger semantics.

## Source code discovery snippets

```bash
rg 'MESA_EXTRACTION_MAX_TOKENS|extraction_max_tokens' .
rg 'nemotron|input_type|passage|query' mesa_memory
rg 'memory/insert|memory/search|sessions/start|mutations/' mesa_api
rg 'search_v4_graph|retrieval_provenance|V4_RRF' .
rg 'publish_source_chunk|execute_publish_delivery|MesaTargetSettings' src tests
rg 'Windows-1254|cp1254|ParsingCoverage|coverage_ratio' src tests
```

Do not paste giant source files into the agent context when a focused `rg`/`sed` range is enough.


## Workspace hygiene discovery

Safe discovery examples:

```bash
find ~/mesa-cert -maxdepth 3 -mindepth 1 -type d -print 2>/dev/null
du -sh ~/mesa-cert/* 2>/dev/null || true
docker ps -a
docker volume ls
docker network ls
```

These are inventory commands, not permission to delete anything.

Do not use broad `rm -rf`, `git clean -fdx`, `docker system prune -a`,
`docker volume prune`, or equivalent destructive cleanup as a shortcut.

## Canonical workspace discovery

Preferred canonical paths:

```text
$HOME/mesa-cert/repos/MESA
$HOME/mesa-cert/repos/MESA_Data
$HOME/mesa-cert/repos/MESA_E2E_Certification
$HOME/mesa-cert/runtime
$HOME/mesa-cert/evidence
$HOME/mesa-cert/archive
$HOME/mesa-cert/cache
$HOME/mesa-cert/secrets
```

Safe repository discovery examples:

```bash
find "$HOME" -maxdepth 4 -type d -name .git -print 2>/dev/null
git -C <candidate> remote -v
git -C <candidate> status --porcelain=v1
```

A folder name is not proof of repository identity.
Verify the Git remote.
