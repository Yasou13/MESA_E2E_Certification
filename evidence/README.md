# evidence/

Per-run raw evidence is written under:

```text
evidence/<RUN_ID>/
```

Evidence is append-only/immutable after its phase closes. Failed and invalidated runs are preserved.

## Never store

- API keys;
- bearer tokens;
- raw secret env files;
- credential-bearing URLs;
- unrestricted environment dumps.

## Preserve

- UTC timestamps;
- exact SHAs/config/release/GT hashes;
- sanitized request shape;
- response status/body needed for proof;
- latency/retry information;
- raw scoring inputs/outputs;
- failure stack traces with secrets redacted;
- invalidation reason and successor RUN_ID.

See `../agent-pack/21_EVIDENCE_MANIFEST_AND_INTEGRITY.md`.

